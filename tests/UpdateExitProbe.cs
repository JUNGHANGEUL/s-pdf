using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

// Test fixture only: waits exactly as the updater does, without installing.
internal static class UpdateExitProbe
{
    private static int Main(string[] args)
    {
        string profile = Environment.GetEnvironmentVariable("SPDF_APPLY_TEST_ROOT");
        string application = Environment.GetEnvironmentVariable("SPDF_APPLY_TEST_APP");
        int index = Array.IndexOf(args, "/wait"), parentId;
        if (index < 0 || !Int32.TryParse(args[index + 1], out parentId)) return 2;
        try { using (Process parent = Process.GetProcessById(parentId)) if (!parent.WaitForExit(8000)) return 3; } catch (ArgumentException) { }
        DateTime until = DateTime.UtcNow.AddSeconds(8);
        while (DateTime.UtcNow < until)
        {
            bool running = false;
            foreach (Process process in Process.GetProcessesByName("S.PDF")) using (process)
            {
                try { if (String.Equals(process.MainModule.FileName, application, StringComparison.OrdinalIgnoreCase)) running = true; }
                catch (InvalidOperationException) { } catch (System.ComponentModel.Win32Exception) { }
            }
            if (!running) { File.WriteAllText(Path.Combine(profile, "applied.txt"), "launcher exited before apply"); return 0; }
            Thread.Sleep(50);
        }
        File.WriteAllText(Path.Combine(profile, "failed.txt"), "launcher and updater waited on inherited pipes"); return 4;
    }
}
