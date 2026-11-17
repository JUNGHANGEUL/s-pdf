using System;
using System.IO;
using Microsoft.Win32;

internal static class FileAssociations
{
    private const string ApplicationKey = @"Software\Classes\Applications\S.PDF.exe";
    private const string DocumentKey = @"Software\Classes\S.PDF.Document";
    private const string OpenWithKey = @"Software\Classes\.pdf\OpenWithProgids";

    internal static void Register(string executable)
    {
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(ApplicationKey))
        {
            key.SetValue("FriendlyAppName", "S.PDF");
            using (RegistryKey types = key.CreateSubKey("SupportedTypes")) types.SetValue(".pdf", "");
            using (RegistryKey command = key.CreateSubKey(@"shell\open\command")) command.SetValue("", "\"" + executable + "\" \"%1\"");
        }
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(DocumentKey))
        {
            key.SetValue("", "S.PDF 문서");
            using (RegistryKey icon = key.CreateSubKey("DefaultIcon")) icon.SetValue("", executable + ",0");
            using (RegistryKey command = key.CreateSubKey(@"shell\open\command")) command.SetValue("", "\"" + executable + "\" \"%1\"");
        }
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(OpenWithKey)) key.SetValue("S.PDF.Document", "");
        // Register Open With only. Do not change the user's default PDF reader.
    }

    internal static void Unregister(string executable)
    {
        string expected = "\"" + executable + "\" \"%1\"";
        foreach (string path in new string[] { ApplicationKey, DocumentKey })
        {
            bool owned;
            using (RegistryKey command = Registry.CurrentUser.OpenSubKey(path + @"\shell\open\command"))
                owned = command != null && String.Equals(command.GetValue("") as string, expected, StringComparison.OrdinalIgnoreCase);
            if (owned) Registry.CurrentUser.DeleteSubKeyTree(path, false);
        }
        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(OpenWithKey, true))
            if (key != null) key.DeleteValue("S.PDF.Document", false);
    }
}
