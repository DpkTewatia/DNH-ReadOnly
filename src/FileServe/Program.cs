using FileServe;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.StaticFiles;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.FileProviders.Physical;
using Microsoft.Extensions.Options;
using Microsoft.Net.Http.Headers;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddSingleton<IValidateOptions<FileVaultOptions>, FileVaultOptionsValidator>();
builder.Services.AddOptions<FileVaultOptions>()
    .Bind(builder.Configuration.GetSection(FileVaultOptions.SectionName))
    .ValidateOnStart();

// Only relevant when another reverse proxy sits in front of IIS. The default
// KnownProxies list is loopback-only, so these headers are ignored unless the
// hop is local -- a spoofed X-Forwarded-For from a real client does not apply.
builder.Services.Configure<ForwardedHeadersOptions>(o =>
{
    o.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
});

var app = builder.Build();

var options = app.Services.GetRequiredService<IOptions<FileVaultOptions>>().Value;
var logger = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("FileServe");

var rootPath = Path.TrimEndingDirectorySeparator(Path.GetFullPath(options.RootPath));

if (!Directory.Exists(rootPath))
{
    // Nearly always either a typo in RootPath or the app pool identity lacking
    // permission to traverse it. Fail at startup rather than 404 on every request.
    logger.LogCritical(
        "FileVault:RootPath '{RootPath}' does not exist or is not readable by the process " +
        "identity ({Identity}). Grant that identity read access to the folder.",
        rootPath,
        Environment.UserName);

    throw new DirectoryNotFoundException($"FileVault:RootPath '{rootPath}' is not accessible.");
}

var fileProvider = new PhysicalFileProvider(
    rootPath,
    options.IncludeHiddenFiles ? ExclusionFilters.None : ExclusionFilters.Sensitive);

var contentTypeProvider = new FileExtensionContentTypeProvider();
foreach (var (extension, mimeType) in options.ContentTypeMappings)
{
    contentTypeProvider.Mappings[extension.StartsWith('.') ? extension : "." + extension] = mimeType;
}

var requestPath = options.RequestPath;

app.UseForwardedHeaders();

// This is a read-only file server, so there is no endpoint routing: the health check
// and the request guard are plain middleware ahead of the static file handler. That
// keeps HealthPath genuinely reserved -- a file of that name can never shadow it.
app.Use(async (context, next) =>
{
    var path = context.Request.Path;

    if (path.Equals(options.HealthPath, StringComparison.OrdinalIgnoreCase))
    {
        await context.Response.WriteAsJsonAsync(new
        {
            status = "ok",
            root = rootPath,
            requestPath = requestPath.Length == 0 ? "/" : requestPath,
        });

        return;
    }

    if (!HttpMethods.IsGet(context.Request.Method) && !HttpMethods.IsHead(context.Request.Method))
    {
        context.Response.StatusCode = StatusCodes.Status405MethodNotAllowed;
        context.Response.Headers.Allow = "GET, HEAD";
        return;
    }

    if (requestPath.Length > 0)
    {
        if (!path.StartsWithSegments(requestPath, StringComparison.OrdinalIgnoreCase, out var remaining))
        {
            await next(context);
            return;
        }

        path = remaining;
    }

    if (!FileVaultGuard.IsServable(path.Value, options, out var reason))
    {
        logger.LogWarning("Refused {Method} {Path} from {RemoteIp}: {Reason}",
            context.Request.Method,
            context.Request.Path.Value,
            context.Connection.RemoteIpAddress,
            reason);

        // 404 rather than 403, so the response does not confirm what exists on disk.
        context.Response.StatusCode = StatusCodes.Status404NotFound;
        return;
    }

    await next(context);
});

if (options.EnableDirectoryBrowsing)
{
    app.UseDefaultFiles(new DefaultFilesOptions
    {
        FileProvider = fileProvider,
        RequestPath = requestPath,
    });

    app.UseDirectoryBrowser(new DirectoryBrowserOptions
    {
        FileProvider = fileProvider,
        RequestPath = requestPath,
    });
}

app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = fileProvider,
    RequestPath = requestPath,
    ServeUnknownFileTypes = options.ServeUnknownFileTypes,
    DefaultContentType = options.DefaultContentType,
    ContentTypeProvider = contentTypeProvider,
    OnPrepareResponse = context =>
    {
        var headers = context.Context.Response.Headers;

        headers.CacheControl = options.CacheMaxAgeSeconds > 0
            ? $"public,max-age={options.CacheMaxAgeSeconds}"
            : "no-cache";

        if (options.ForceDownload)
        {
            var disposition = new ContentDispositionHeaderValue("attachment");
            disposition.SetHttpFileName(context.File.Name);
            headers.ContentDisposition = disposition.ToString();
        }
    },
});

// Reached only when the request matched no file on disk.
app.Run(async context =>
{
    context.Response.StatusCode = StatusCodes.Status404NotFound;

    await context.Response.WriteAsJsonAsync(new
    {
        status = 404,
        message = "File not found.",
        path = context.Request.Path.Value,
    });
});

logger.LogInformation(
    "Serving {RootPath} at {RequestPath} (directory browsing: {Browsing}, forced download: {Download})",
    rootPath,
    requestPath.Length == 0 ? "/" : requestPath,
    options.EnableDirectoryBrowsing,
    options.ForceDownload);

app.Run();
