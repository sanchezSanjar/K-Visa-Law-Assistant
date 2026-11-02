// KVisaLaw.exe: starts the K-Visa Law Assistant server hidden and opens the chat in the browser.
// Build: launcher\build.bat
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("K-Visa Law Assistant")]
[assembly: System.Reflection.AssemblyProduct("K-Visa Law Assistant")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

static class KVisaLauncher
{
    // Windows (Hyper-V/WSL) reserves changing port ranges, so ask the OS for a free port each start
    // and remember it in kvisa.port to find a server that is already running.
    static int Port;
    static string Url { get { return "http://localhost:" + Port; } }

    [STAThread]
    static int Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(dir, @".venv\Scripts\python.exe");
        string log = Path.Combine(dir, "kvisa.log");
        string portFile = Path.Combine(dir, "kvisa.port");

        int saved;
        if (File.Exists(portFile) && int.TryParse(File.ReadAllText(portFile).Trim(), out saved))
        {
            Port = saved;
            if (IsRunning())
            {
                OpenBrowser();
                return 0;
            }
        }
        if (!File.Exists(Path.Combine(dir, @"kvisa\server.py")))
            return Warn("kvisa\\server.py was not found. Keep KVisaLaw.exe inside the project folder " +
                        "(use a shortcut to start it from the Desktop).");
        if (!File.Exists(python) || !Directory.Exists(Path.Combine(dir, @"models\Qwen3-4B-Instruct-2507")) ||
            !Directory.Exists(Path.Combine(dir, "index")))
            return Warn("K-Visa Law Assistant is not set up yet.\n\nDouble-click INSTALL_WINDOWS.bat " +
                        "(needs internet once, about 15 GB), then open KVisaLaw.exe again.");

        Port = FreePort();
        File.WriteAllText(portFile, Port.ToString());
        string command = "/c \"\"" + python + "\" -X utf8 -m kvisa.server --port " + Port + " > kvisa.log 2>&1\"";
        Process server;
        try
        {
            server = Process.Start(new ProcessStartInfo("cmd.exe", command)
            {
                WorkingDirectory = dir,
                UseShellExecute = false,
                CreateNoWindow = true,
            });
        }
        catch (Exception ex)
        {
            return Warn("Could not start Python: " + ex.Message);
        }

        Application.EnableVisualStyles();
        var splash = new Form
        {
            Text = "K-Visa Law Assistant",
            Size = new Size(400, 150),
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterScreen,
            MaximizeBox = false,
            MinimizeBox = false,
            BackColor = Color.White,
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath),
        };
        splash.Controls.Add(new Label
        {
            Text = "K-Visa Law Assistant 시작 중...\nStarting. The chat opens in your browser.",
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            Font = new Font("Malgun Gothic", 10),
            ForeColor = Color.FromArgb(11, 61, 145),
        });

        int result = 0;
        var started = DateTime.Now;
        var timer = new Timer { Interval = 500 };
        timer.Tick += (s, e) =>
        {
            if (IsRunning())
            {
                timer.Stop();
                OpenBrowser();
                splash.Close();
            }
            else if (server.HasExited || (DateTime.Now - started).TotalSeconds > 120)
            {
                timer.Stop();
                splash.Hide();
                result = Warn("K-Visa Law Assistant could not start.\n\n" + Tail(log) + "\n\nLog: " + log);
                splash.Close();
            }
        };
        splash.Shown += (s, e) => timer.Start();
        Application.Run(splash);
        return result;
    }

    static int FreePort()
    {
        var listener = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        int port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    static bool IsRunning()
    {
        try
        {
            // 127.0.0.1 avoids a slow IPv6 attempt for "localhost".
            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + Port + "/api/health");
            request.Timeout = 400;
            using (var response = (HttpWebResponse)request.GetResponse())
                return response.StatusCode == HttpStatusCode.OK;
        }
        catch (WebException)
        {
            return false;
        }
    }

    static void OpenBrowser()
    {
        Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
    }

    static string Tail(string path)
    {
        if (!File.Exists(path))
            return "(no log)";
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        using (var reader = new StreamReader(stream))
        {
            var lines = reader.ReadToEnd().Split('\n');
            return string.Join("\n", lines.Skip(Math.Max(0, lines.Length - 10)));
        }
    }

    static int Warn(string message)
    {
        MessageBox.Show(message, "K-Visa Law Assistant", MessageBoxButtons.OK, MessageBoxIcon.Information);
        return 1;
    }
}
