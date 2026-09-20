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
    /// Absolute path of the folder to serve, e.g. "D:\SharedFiles". This folder is
    /// outside the IIS application directory, and must not contain or sit inside it.
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

    /// <summary>
    /// Include files marked hidden/system, and names beginning with a dot. Turning this on
    /// does not expose blocked names: ".env" and ".git" are on the block lists in their own right.
    /// </summary>
    public bool IncludeHiddenFiles { get; set; }

    /// <summary>
    /// If non-empty, only these extensions are served and everything else is refused.
    /// This is the strongest control available -- prefer it when the answer is
    /// "only PDFs and images". Matched against the final extension only.
    /// </summary>
    public string[] AllowedExtensions { get; set; } = [];

    /// <summary>
    /// Extensions that are never served, applied after <see cref="AllowedExtensions"/>.
    /// Matched against every dot-separated suffix, not just the last one, so
    /// "web.config.bak" is refused for containing ".config" even though it ends in ".bak".
    /// </summary>
    public string[] BlockedExtensions { get; set; } =
    [
        // Server-side source and markup
        ".cs", ".vb", ".fs", ".cshtml", ".vbhtml", ".razor",
        ".aspx", ".ascx", ".asax", ".ashx", ".asmx", ".master", ".svc", ".axd",
        ".asp", ".asa", ".cdx",
        ".jsp", ".jspx", ".php", ".php5", ".phtml", ".py", ".rb", ".pl", ".cgi",

        // Configuration and project files
        ".config", ".settings", ".pubxml", ".publishsettings", ".user",
        ".csproj", ".vbproj", ".fsproj", ".sln", ".props", ".targets", ".nuspec",

        // Credentials, keys and certificates
        ".pfx", ".p12", ".key", ".pem", ".cer", ".crt", ".der",
        ".jks", ".keystore", ".env", ".ovpn", ".rdp", ".ppk", ".kdbx",

        // Executables and scripts
        ".exe", ".dll", ".msi", ".com", ".scr", ".jar",
        ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".wsf", ".sh",

        // Databases
        ".mdf", ".ldf", ".sdf", ".mdb", ".accdb", ".db", ".sqlite", ".sqlite3",

        // Backups and editor leftovers, which usually shadow one of the above
        ".bak", ".backup", ".old", ".orig", ".save", ".swp", ".tmp",
    ];

    /// <summary>
    /// File names that are never served, regardless of extension. Supports the
    /// wildcards "*" and "?", and is matched case-insensitively against the file name.
    /// Catches sensitive files whose extension is otherwise legitimate, such as
    /// "appsettings.Production.json".
    /// </summary>
    public string[] BlockedFileNames { get; set; } =
    [
        "appsettings*.json", "secrets*.json", "launchsettings.json",
        "*.deps.json", "*.runtimeconfig.json", "*.staticwebassets*.json",
        "web.config*", "app.config*", "machine.config*", "packages.config",
        "connectionstrings*", "global.asax*",
        ".env*", ".htaccess", ".htpasswd", ".npmrc", ".netrc", ".git*", ".dockerignore",
        "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.pub",
        "thumbs.db", "desktop.ini",
    ];

    /// <summary>
    /// Folder names that are never traversed. Any request whose path contains one of
    /// these segments is refused, and directory listings omit them.
    /// </summary>
    public string[] BlockedDirectories { get; set; } =
    [
        "bin", "obj", "App_Data", "App_Code", "App_GlobalResources", "App_LocalResources",
        ".git", ".svn", ".hg", ".vs", ".vscode", ".idea", "node_modules", "__pycache__",
    ];

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
