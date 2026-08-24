using System.Diagnostics.CodeAnalysis;
using System.IO.Enumeration;

namespace FileServe;

/// <summary>
/// The content policy: which paths, folders and file names may leave the vault.
/// Enforced in two places -- <see cref="VaultFileProvider"/> applies it with definite
/// knowledge of whether a target is a file or a folder, and the request middleware
/// applies it early so refusals are logged before any disk access.
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

    /// <summary>
    /// Checks a whole request path against the policy.
    /// </summary>
    /// <param name="subPath">Decoded path relative to the vault root, e.g. "/reports/q1.pdf".</param>
    /// <param name="treatLastSegmentAsDirectory">
    /// When true the final segment is judged as a folder name; when false, as a file name.
    /// Callers that cannot tell should pass true -- <see cref="VaultFileProvider"/> re-checks
    /// with the real answer before anything is served.
    /// </param>
    /// <param name="reason">Why the request was refused; only set when this returns false.</param>
    public static bool IsServable(
        string? subPath,
        FileVaultOptions options,
        bool treatLastSegmentAsDirectory,
        [NotNullWhen(false)] out string? reason)
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
        if (segments.Length == 0)
        {
            return true;
        }

        // A trailing slash is an unambiguous folder request.
        var lastIsDirectory = treatLastSegmentAsDirectory || subPath.EndsWith('/');

        for (var i = 0; i < segments.Length; i++)
        {
            var segment = segments[i];

            if (!IsStructurallySafe(segment, out reason))
            {
                return false;
            }

            var isLast = i == segments.Length - 1;

            if (!isLast || lastIsDirectory)
            {
                if (IsBlockedDirectoryName(segment, options))
                {
                    reason = $"folder '{segment}' is in BlockedDirectories";
                    return false;
                }
            }
            else if (!IsFileNameServable(segment, options, out reason))
            {
                return false;
            }
        }

        return true;
    }

    /// <summary>Path-shape checks that apply to folders and files alike.</summary>
    private static bool IsStructurallySafe(string segment, [NotNullWhen(false)] out string? reason)
    {
        reason = null;

        if (segment is "." or "..")
        {
            reason = "path traversal";
            return false;
        }

        // "web.config." and "web.config " both resolve to "web.config" on Windows, which
        // would otherwise sidestep every name and extension rule below.
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

        return true;
    }

    public static bool IsBlockedDirectoryName(string name, FileVaultOptions options)
    {
        foreach (var blocked in options.BlockedDirectories)
        {
            if (name.Equals(blocked, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>Applies the allowlist, the name block list, then the extension block list.</summary>
    public static bool IsFileNameServable(
        string name,
        FileVaultOptions options,
        [NotNullWhen(false)] out string? reason)
    {
        reason = null;

        var extension = Path.GetExtension(name);

        if (options.AllowedExtensions.Length > 0 && !MatchesExtension(options.AllowedExtensions, extension))
        {
            reason = extension.Length == 0
                ? "file has no extension and AllowedExtensions is set"
                : $"extension '{extension}' is not in AllowedExtensions";
            return false;
        }

        foreach (var pattern in options.BlockedFileNames)
        {
            if (FileSystemName.MatchesSimpleExpression(pattern, name, ignoreCase: true))
            {
                reason = $"name matches BlockedFileNames pattern '{pattern}'";
                return false;
            }
        }

        // Every suffix is checked, not just the last, so "web.config.bak" and
        // "appsettings.json.old" are caught by ".config" and by the name patterns.
        var parts = name.Split('.');
        for (var i = 1; i < parts.Length; i++)
        {
            var suffix = "." + parts[i];
            if (MatchesExtension(options.BlockedExtensions, suffix))
            {
                reason = $"extension '{suffix}' is in BlockedExtensions";
                return false;
            }
        }

        return true;
    }

    private static bool MatchesExtension(string[] extensions, string extension)
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
