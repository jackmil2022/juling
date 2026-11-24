using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("剧灵")]
[assembly: AssemblyProduct("剧灵")]

static class Launcher
{
    [STAThread]
    static void Main()
    {
        string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, @"..\.."));
        string electron = Path.Combine(root, @"frontend\node_modules\electron\dist\electron.exe");
        try
        {
            if (!File.Exists(electron))
                throw new FileNotFoundException("缺少桌面运行环境，请重新运行 desktop/build.ps1。");
            Process.Start(new ProcessStartInfo {
                FileName = electron,
                Arguments = "\"" + Path.Combine(root, @"desktop\main.cjs") + "\"",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true
            });
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "剧灵 启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
