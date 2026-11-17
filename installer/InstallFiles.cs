using System;
using System.Collections.Generic;
using System.IO;

internal static class InstallFiles
{
    // Only remove packaged files. Documents added by the user remain in place.
    internal static void RemoveOwned(string path)
    {
        string manifest = Path.Combine(path, "install-manifest.txt");
        string marker = Path.Combine(path, ".spdf-install");
        if (!File.Exists(marker) || !File.Exists(manifest)) throw new IOException("설치 파일 목록을 확인할 수 없습니다.");
        string prefix = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        List<string> targets = new List<string>();
        HashSet<string> folders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string relative in File.ReadAllLines(manifest))
        {
            if (String.IsNullOrWhiteSpace(relative)) continue;
            string target = Path.GetFullPath(Path.Combine(path, relative));
            if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("설치 파일 경로가 올바르지 않습니다.");
            targets.Add(target);
            string parent = Path.GetDirectoryName(target);
            while (parent != null && parent.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                folders.Add(parent); parent = Path.GetDirectoryName(parent);
            }
        }
        foreach (string target in targets) if (File.Exists(target)) File.Delete(target);
        List<string> orderedFolders = new List<string>(folders);
        orderedFolders.Sort(delegate(string a, string b) { return b.Length.CompareTo(a.Length); });
        foreach (string folder in orderedFolders)
            if (Directory.Exists(folder) && Directory.GetFileSystemEntries(folder).Length == 0) Directory.Delete(folder);
        File.Delete(manifest); File.Delete(marker);
        if (Directory.GetFileSystemEntries(path).Length == 0) Directory.Delete(path);
    }
}
