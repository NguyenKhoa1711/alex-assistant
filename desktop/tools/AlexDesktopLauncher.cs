using System;
using System.IO;
using System.Diagnostics;
using System.Windows.Forms;

internal static class AlexDesktopLauncher {
    [STAThread]
    static int Main() {
        try {
            string folder = AppDomain.CurrentDomain.BaseDirectory;
            string root = Path.GetFullPath(Path.Combine(folder, "..", "trợ lý ảo-local", "outputs", "Bionic-pet"));
            string python = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
            string script = Path.Combine(root, "launch.py");
            if (!File.Exists(python) || !File.Exists(script))
                throw new IOException("Chưa tìm thấy bộ xử lý Alex trong thư mục dự án. Hãy giữ Alex Desktop cùng thư mục dự án trợ lý ảo.");
            Process.Start(new ProcessStartInfo {
                FileName = python,
                Arguments = "\"" + script + "\" --app",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            });
            return 0;
        } catch (Exception ex) {
            MessageBox.Show(ex.Message, "Alex — Chưa mở được ứng dụng", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
    }
}
