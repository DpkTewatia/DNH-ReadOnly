using Microsoft.Extensions.Options;

namespace FileServe;

/// <summary>
/// Configuration for the folder that lives outside the application directory.
/// Bound from the "FileVault" section of appsettings.json / environment variables.
/// </summary>
public sealed class FileVaultOptions
{
    public const string SectionName = "FileVault";

    /// <summary>
    /// Absolute path of the folder to serve, e.g. "D:\SharedFiles" or "\\fileserver\share\public".
    /// This folder is outside the IIS application directory.
    /// </summary>
    public string RootPath { get; set; } = string.Empty;

    /// <summary>
    /// URL prefix the files are exposed under. Empty string serves them at the site root
    /// (https://domain/report.pdf); "/files" serves them at https://domain/files/report.pdf.
    /// </summary>
    public string RequestPath { get; set; } = string.Empty;

    /// <summary>Serve files whose extension has no known MIME type, using <see cref="DefaultContentType"/>.</summary>
    public bool ServeUnknownFileTypes { get; set; } = true;

    public string DefaultContentType { get; set; } = "application/octet-stream";

    /// <summary>Render an HTML index when a folder (rather than a file) is requested.</summary>
    public bool EnableDirectoryBrowsing { get; set; }

    /// <summary>Send Content-Disposition: attachment so browsers download instead of rendering inline.</summary>
    public bool ForceDownload { get; set; }

    /// <summary>Include files marked hidden/system, and folders beginning with a dot.</summary>
    public bool IncludeHiddenFiles { get; set; }

    /// <summary>If non-empty, only these extensions are served. Example: [ ".pdf", ".png" ].</summary>
    public string[] AllowedExtensions { get; set; } = [];

    /// <summary>Extensions that are never served. Applied after <see cref="AllowedExtensions"/>.</summary>
    public string[] BlockedExtensions { get; set; } =
        [".config", ".exe", ".dll", ".ps1", ".bat", ".cmd", ".pfx", ".key"];

    /// <summary>Value for the Cache-Control max-age header on served files. 0 disables caching.</summary>
    public int CacheMaxAgeSeconds { get; set; }

    /// <summary>Extra or overriding MIME mappings, e.g. { ".log": "text/plain" }.</summary>
    public Dictionary<string, string> ContentTypeMappings { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>Path of the liveness endpoint. Reserved, so it is never treated as a file name.</summary>
    public string HealthPath { get; set; } = "/healthz";
}

/// <summary>Fails startup loudly rather than letting the site come up serving nothing.</summary>
public sealed class FileVaultOptionsValidator : IValidateOptions<FileVaultOptions>
{
    public ValidateOptionsResult Validate(string? name, FileVaultOptions options)
    {
        List<string> failures = [];

        if (string.IsNullOrWhiteSpace(options.RootPath))
        {
            failures.Add($"{FileVaultOptions.SectionName}:RootPath is required.");
        }
        else if (!Path.IsPathFullyQualified(options.RootPath))
        {
            failures.Add($"{FileVaultOptions.SectionName}:RootPath must be an absolute path, " +
                         $"but was '{options.RootPath}'.");
        }

        if (options.RequestPath.Length > 0 && !options.RequestPath.StartsWith('/'))
        {
            failures.Add($"{FileVaultOptions.SectionName}:RequestPath must start with '/' " +
                         $"or be empty, but was '{options.RequestPath}'.");
        }

        if (options.RequestPath.EndsWith('/'))
        {
            failures.Add($"{FileVaultOptions.SectionName}:RequestPath must not end with '/'.");
        }

        return failures.Count > 0
            ? ValidateOptionsResult.Fail(failures)
            : ValidateOptionsResult.Success;
    }
}
