using System.Collections;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Primitives;

namespace FileServe;

/// <summary>
/// Wraps the physical provider and applies <see cref="FileVaultGuard"/> to everything
/// it hands out. Enforcing the policy here rather than only in middleware means every
/// consumer inherits it: the static file handler, the default-file handler, and the
/// directory browser, which would otherwise list the names of files it cannot serve.
/// </summary>
/// <remarks>
/// This layer knows from <see cref="IFileInfo.IsDirectory"/> whether a target is a file
/// or a folder, so it judges extensionless names such as "id_rsa" correctly where the
/// middleware can only guess from the URL.
/// </remarks>
public sealed class VaultFileProvider(IFileProvider inner, FileVaultOptions options, string rootPath)
    : IFileProvider
{
    public IFileInfo GetFileInfo(string subpath)
    {
        var info = inner.GetFileInfo(subpath);

        // Missing files fall through unchanged so they 404 the ordinary way.
        if (!info.Exists)
        {
            return info;
        }

        return IsServable(subpath, info, info.IsDirectory)
            ? info
            : new NotFoundFileInfo(info.Name);
    }

    public IDirectoryContents GetDirectoryContents(string subpath)
    {
        if (!FileVaultGuard.IsServable(subpath, options, treatLastSegmentAsDirectory: true, out _))
        {
            return NotFoundDirectoryContents.Singleton;
        }

        var contents = inner.GetDirectoryContents(subpath);

        return contents.Exists
            ? new FilteredDirectoryContents(contents.Where(IsVisible))
            : contents;
    }

    public IChangeToken Watch(string filter) => inner.Watch(filter);

    /// <summary>
    /// Requires the policy to pass against both the spelling in the URL and the real
    /// path on disk.
    /// </summary>
    /// <remarks>
    /// The two can differ. NTFS keeps a legacy 8.3 alias for most files, and Windows
    /// opens a file by either name, so a request for "APPSET~1.JSO" reads
    /// "appsettings.json": the URL ends in ".JSO", matches no rule, and would be served
    /// on its own spelling. Checking the resolved path closes that, and also rejects any
    /// resolved path that leaves the vault, since GetRelativePath then yields a ".." prefix.
    /// </remarks>
    private bool IsServable(string subpath, IFileInfo info, bool isDirectory)
    {
        if (!FileVaultGuard.IsServable(subpath, options, isDirectory, out _))
        {
            return false;
        }

        if (info.PhysicalPath is not { } physicalPath)
        {
            return true;
        }

        var resolved = "/" + Path.GetRelativePath(rootPath, physicalPath)
            .Replace(Path.DirectorySeparatorChar, '/');

        return string.Equals(resolved, subpath, StringComparison.OrdinalIgnoreCase)
               || FileVaultGuard.IsServable(resolved, options, isDirectory, out _);
    }

    private bool IsVisible(IFileInfo entry) =>
        entry.IsDirectory
            ? !FileVaultGuard.IsBlockedDirectoryName(entry.Name, options)
            : FileVaultGuard.IsFileNameServable(entry.Name, options, out _);

    private sealed class FilteredDirectoryContents(IEnumerable<IFileInfo> entries) : IDirectoryContents
    {
        public bool Exists => true;

        public IEnumerator<IFileInfo> GetEnumerator() => entries.GetEnumerator();

        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
