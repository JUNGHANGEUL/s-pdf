using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

internal static class InstallerTests
{
    private static void Check(bool value, string text) { if (!value) throw new Exception(text); }
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            string root = Path.GetFullPath(args[0]), target = Path.Combine(root, "application"), profile = Path.Combine(root, "profile");
            Environment.SetEnvironmentVariable("SPDF_DATA_DIR", profile);
            SetupProgram.Install(false, null, null, null, target, false);
            Check(File.Exists(Path.Combine(target, ".spdf-install")), "Initial installation marker missing");
            File.WriteAllText(Path.Combine(target, "app.dat"), "previous version");
            File.WriteAllText(Path.Combine(target, "user-notes.txt"), "keep user data");
            bool cancel = false;
            try { SetupProgram.Install(false, null, (value, text) => { cancel = true; }, () => cancel, target, false); throw new Exception("Expected cancellation"); }
            catch (OperationCanceledException) { }
            Check(File.ReadAllText(Path.Combine(target, "app.dat")) == "previous version", "Cancellation changed current install");
            try { SetupProgram.Install(false, null, (value, text) => { if (value == 90) throw new IOException("simulate deployment failure"); }, null, target, false); throw new Exception("Expected rollback"); }
            catch (IOException) { }
            Check(File.ReadAllText(Path.Combine(target, "app.dat")) == "previous version", "Rollback failed");
            Check(File.ReadAllText(Path.Combine(target, "user-notes.txt")) == "keep user data", "Rollback lost user file");
            SetupProgram.Install(false, null, null, null, target, false);
            Check(File.ReadAllText(Path.Combine(target, "app.dat")) == "new version", "New version not deployed");
            Check(File.ReadAllText(Path.Combine(target, "user-notes.txt")) == "keep user data", "Update lost user file");
            Directory.CreateDirectory(profile); File.WriteAllText(Path.Combine(profile, "settings.json"), "{\"theme\":\"dark\",\"recent\":[\"example.pdf\"]}");
            SetupProgram.SaveUpdatePreference(false);
            Check(Object.Equals(SetupProgram.ReadSettings(Path.Combine(profile, "settings.json"))["automatic_updates"], false), "Update preference not saved");
            Check(Convert.ToString(SetupProgram.ReadSettings(Path.Combine(profile, "settings.json"))["theme"]) == "dark", "Existing settings lost");
            SetupProgram.SaveUpdatePreference(true);
            using (SetupForm form = new SetupForm(true)) using (Bitmap image = new Bitmap(form.Width, form.Height))
            { form.Opacity = 0; form.ShowInTaskbar = false; form.Show(); Application.DoEvents(); form.DrawToBitmap(image, new Rectangle(Point.Empty, form.Size)); image.Save(Path.Combine(root, "installer.png")); }
            Console.WriteLine("PASS: install, cancellation, deployment rollback, replacement, user files, preferences, installer render."); return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
