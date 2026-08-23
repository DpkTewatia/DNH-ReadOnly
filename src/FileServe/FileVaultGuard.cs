using System.Diagnostics.CodeAnalysis;

namespace FileServe;

/// <summary>
/// Defence-in-depth checks applied to the requested sub-path before the static file
/// middleware touches the disk. The middleware already blocks traversal, but this layer
/// also enforces the extension policy and rejects Windows-specific path tricks
/// (alternate data streams, reserved device names, trailing dots) that can otherwise
/// resolve to a different file than the URL suggests.
/// </summary>
public static class FileVaultGuard
{
    private static readonly char[] ForbiddenChars =
    [
        '<', '>', '|', '*', ':', '"',
        (char)0x5C, // backslash: the URL separator is '/', so a literal one is always suspect
        (char)0x00, // NUL: truncates the path in some downstream APIs
    ];

    private static readonly HashSet<string> ReservedDeviceNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    };

    /// <param name="subPath">Decoded path relative to the vault root, e.g. "/reports/q1.pdf".</param>
    /// <param name="reason">Why the request was rejected; only set when this returns false.</param>
    public static bool IsServable(string? subPath, FileVaultOptions options, [NotNullWhen(false)] out string? reason)
    {
        reason = null;

        if (string.IsNullOrEmpty(subPath) || subPath == "/")
        {
            return true;
        }

        if (subPath.IndexOfAny(ForbiddenChars) >= 0)
        {
            reason = "path contains a character that is not valid in a file name";
            return false;
        }

        var segments = subPath.Split('/', StringSplitOptions.RemoveEmptyEntries);

        foreach (var segment in segments)
        {
            if (segment is "." or "..")
            {
                reason = "path traversal";
                return false;
            }

            // "file.txt." and "file.txt " both resolve to "file.txt" on Windows, which would
            // sidestep the extension policy checked below.
            if (segment.EndsWith('.') || segment.EndsWith(' '))
            {
                reason = "path segment ends with a dot or space";
                return false;
            }

            var stem = segment.Split('.', 2)[0];
            if (ReservedDeviceNames.Contains(stem))
            {
                reason = $"path segment '{segment}' is a reserved device name";
                return false;
            }
        }

        // A trailing slash means a directory was requested; the extension policy does not apply.
        if (subPath.EndsWith('/'))
        {
            return true;
        }

        var extension = Path.GetExtension(segments[^1]);

        if (options.AllowedExtensions.Length > 0 && !Contains(options.AllowedExtensions, extension))
        {
            reason = extension.Length == 0
                ? "file has no extension and AllowedExtensions is set"
                : $"extension '{extension}' is not in AllowedExtensions";
            return false;
        }

        if (Contains(options.BlockedExtensions, extension))
        {
            reason = $"extension '{extension}' is in BlockedExtensions";
            return false;
        }

        return true;
    }

    private static bool Contains(string[] extensions, string extension)
    {
        foreach (var candidate in extensions)
        {
            var normalized = candidate.StartsWith('.') ? candidate : "." + candidate;
            if (normalized.Equals(extension, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }
}
