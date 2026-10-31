using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using System.Windows.Interop;
using Microsoft.Web.WebView2.Core;

namespace JarvisLocal.Desktop;

public partial class MainWindow : Window
{
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(3) };
    private string? _token;
    private int _port;
    private bool _closing;

    public MainWindow()
    {
        InitializeComponent();
        SourceInitialized += OnSourceInitialized;
        Loaded += async (_, _) => await InitializeAsync();
        Closing += async (_, args) =>
        {
            if (_closing)
                return;
            args.Cancel = true;
            _closing = true;
            await StopLocalServerAsync();
            Close();
        };
    }

    private async Task InitializeAsync()
    {
        try
        {
            var root = FindProjectRoot();
            await EnsureControlCenterAsync(root);
            var endpoint = await ReadEndpointAsync(root);
            _port = endpoint.Port;
            _token = endpoint.Token;

            var userData = Path.Combine(root, "data", "desktop", "webview2");
            Directory.CreateDirectory(userData);
            var environment = await CoreWebView2Environment.CreateAsync(
                userDataFolder: userData,
                options: new CoreWebView2EnvironmentOptions("--disable-features=msEdgeSidebarV2"));
            await Web.EnsureCoreWebView2Async(environment);
            ConfigureWebView();
            Web.NavigationCompleted += (_, args) =>
            {
                if (args.IsSuccess)
                    Loading.Visibility = Visibility.Collapsed;
                else
                    ShowFailure($"La interfaz local no respondió: {args.WebErrorStatus}");
            };
            Web.Source = new Uri($"http://127.0.0.1:{_port}/?token={Uri.EscapeDataString(_token)}");
        }
        catch (Exception exc)
        {
            ShowFailure(exc.Message);
        }
    }

    private void ConfigureWebView()
    {
        var settings = Web.CoreWebView2.Settings;
        settings.AreDevToolsEnabled = false;
        settings.AreDefaultContextMenusEnabled = false;
        settings.AreBrowserAcceleratorKeysEnabled = false;
        settings.IsStatusBarEnabled = false;
        settings.IsZoomControlEnabled = false;
        Web.CoreWebView2.NavigationStarting += (_, args) =>
        {
            if (!Uri.TryCreate(args.Uri, UriKind.Absolute, out var uri) ||
                uri.Scheme != "http" ||
                uri.Port != _port ||
                uri.Host is not ("127.0.0.1" or "localhost"))
            {
                args.Cancel = true;
            }
        };
        Web.CoreWebView2.NewWindowRequested += (_, args) => args.Handled = true;
        // Todo permiso web se niega, salvo el micrófono para la interfaz de
        // OpenJarvis incrustada en el panel: loopback, en un puerto distinto
        // del centro de control (el CSP del panel solo admite ese servidor).
        Web.CoreWebView2.PermissionRequested += (_, args) =>
            args.State = IsOpenJarvisMicrophone(args.PermissionKind, args.Uri, _port)
                ? CoreWebView2PermissionState.Allow
                : CoreWebView2PermissionState.Deny;
    }

    internal static bool IsOpenJarvisMicrophone(CoreWebView2PermissionKind kind, string uri, int controlCenterPort) =>
        kind == CoreWebView2PermissionKind.Microphone &&
        Uri.TryCreate(uri, UriKind.Absolute, out var origin) &&
        origin.Scheme == Uri.UriSchemeHttp &&
        origin.Host == "127.0.0.1" &&
        origin.Port != controlCenterPort;

    private static async Task EnsureControlCenterAsync(string root)
    {
        var python = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(python))
            throw new FileNotFoundException("No existe el entorno Python local de Mark Scout.", python);
        var info = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "-m jarvis_local.control_center --launch --no-browser",
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        using var process = Process.Start(info) ?? throw new InvalidOperationException("No se pudo iniciar el núcleo local.");
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await process.WaitForExitAsync(timeout.Token);
        if (process.ExitCode != 0)
            throw new InvalidOperationException($"El núcleo local terminó con código {process.ExitCode}.");
    }

    private static async Task<(int Port, string Token)> ReadEndpointAsync(string root)
    {
        var path = Path.Combine(root, "data", "control_center", "endpoint.json");
        for (var attempt = 0; attempt < 40; attempt++)
        {
            try
            {
                using var document = JsonDocument.Parse(await File.ReadAllTextAsync(path));
                var rootElement = document.RootElement;
                var bind = rootElement.GetProperty("bind").GetString();
                var port = rootElement.GetProperty("port").GetInt32();
                var token = rootElement.GetProperty("token").GetString();
                if (bind == "127.0.0.1" && port is > 0 and <= 65535 && !string.IsNullOrWhiteSpace(token))
                    return (port, token);
            }
            catch (IOException) { }
            catch (JsonException) { }
            await Task.Delay(150);
        }
        throw new InvalidOperationException("No se encontró un endpoint local válido.");
    }

    private async Task StopLocalServerAsync()
    {
        if (_port == 0 || string.IsNullOrWhiteSpace(_token))
            return;
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, $"http://127.0.0.1:{_port}/api/server/stop");
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);
            request.Content = new StringContent("{}", System.Text.Encoding.UTF8, "application/json");
            await _http.SendAsync(request);
        }
        catch (HttpRequestException) { }
        catch (TaskCanceledException) { }
    }

    private static string FindProjectRoot()
    {
        var configured = Environment.GetEnvironmentVariable("JARVISLOCAL_ROOT");
        if (!string.IsNullOrWhiteSpace(configured) && File.Exists(Path.Combine(configured, "config", "jarvis.toml")))
            return Path.GetFullPath(configured);
        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "config", "jarvis.toml")))
                return current.FullName;
            current = current.Parent;
        }
        throw new DirectoryNotFoundException("No se pudo localizar la carpeta técnica de Mark Scout.");
    }

    private void ShowFailure(string message)
    {
        LoadingText.Text = "ERROR AL INICIAR\n\n" + message;
        LoadingText.Foreground = System.Windows.Media.Brushes.IndianRed;
        LoadingText.TextAlignment = TextAlignment.Center;
    }

    private void OnSourceInitialized(object? sender, EventArgs e)
    {
        var source = HwndSource.FromHwnd(new WindowInteropHelper(this).Handle);
        source?.AddHook(WindowProcedure);
    }

    private nint WindowProcedure(
        nint windowHandle,
        int message,
        nint wordParameter,
        nint longParameter,
        ref bool handled)
    {
        if (message == NativeMethods.ActivateMessage)
        {
            if (WindowState == WindowState.Minimized)
                WindowState = WindowState.Normal;
            Activate();
            Topmost = true;
            Topmost = false;
            Focus();
            handled = true;
        }
        return nint.Zero;
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
            ToggleMaximize();
        else
            DragMove();
    }

    private void Minimize_Click(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;
    private void Maximize_Click(object sender, RoutedEventArgs e) => ToggleMaximize();
    private void Close_Click(object sender, RoutedEventArgs e) => Close();
    private void ToggleMaximize() => WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
}
