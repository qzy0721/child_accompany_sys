using System.Diagnostics;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace VirtualCompanion.Desktop;

internal sealed class MainForm : Form
{
    private const string WebViewRuntimeDownloadUrl = "https://developer.microsoft.com/microsoft-edge/webview2/";
    private readonly CancellationTokenSource _shutdown = new();
    private readonly ServerHost _serverHost;
    private readonly WebView2 _webView = new() { Dock = DockStyle.Fill, Visible = false };
    private readonly Panel _statusPanel = new() { Dock = DockStyle.Fill, BackColor = Color.FromArgb(246, 247, 251) };
    private readonly Label _statusLabel = new()
    {
        AutoSize = false,
        Dock = DockStyle.Top,
        Width = 620,
        Height = 64,
        TextAlign = ContentAlignment.MiddleCenter,
        Font = new Font("Microsoft YaHei UI", 11F, FontStyle.Regular),
        ForeColor = Color.FromArgb(77, 78, 97),
    };
    private readonly ProgressBar _progress = new()
    {
        Width = 280,
        Height = 5,
        Style = ProgressBarStyle.Marquee,
        MarqueeAnimationSpeed = 28,
    };
    private readonly Button _retryButton = new() { Text = "重试", AutoSize = true, Visible = false };
    private readonly Button _openLogButton = new() { Text = "打开日志", AutoSize = true, Visible = false };
    private readonly Button _runtimeButton = new() { Text = "安装 WebView2", AutoSize = true, Visible = false };
    private bool _hostRunning;
    private bool _webViewInitialized;

    public MainForm(ShellOptions options)
    {
        _serverHost = new ServerHost(options);

        Text = "虚拟陪伴";
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(1280, 800);
        MinimumSize = new Size(960, 640);
        BackColor = Color.White;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

        BuildStatusPanel();
        Controls.Add(_webView);
        Controls.Add(_statusPanel);

        Shown += (_, _) => StartHost();
        FormClosing += OnFormClosing;
        _retryButton.Click += (_, _) => StartHost();
        _openLogButton.Click += (_, _) => OpenPath(_serverHost.ServerLogPath);
        _runtimeButton.Click += (_, _) => OpenPath(WebViewRuntimeDownloadUrl);
    }

    private void BuildStatusPanel()
    {
        var content = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
        };
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        content.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        content.RowStyles.Add(new RowStyle(SizeType.Percent, 50));

        var center = new FlowLayoutPanel
        {
            AutoSize = true,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            Anchor = AnchorStyles.None,
            Padding = new Padding(24),
        };
        var actions = new FlowLayoutPanel
        {
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Anchor = AnchorStyles.None,
        };
        actions.Controls.Add(_retryButton);
        actions.Controls.Add(_openLogButton);
        actions.Controls.Add(_runtimeButton);

        center.Controls.Add(_statusLabel);
        center.Controls.Add(_progress);
        center.Controls.Add(actions);
        content.Controls.Add(center, 0, 1);
        _statusPanel.Controls.Add(content);
    }

    private async void StartHost()
    {
        if (_hostRunning || _shutdown.IsCancellationRequested)
        {
            return;
        }

        _hostRunning = true;
        ShowLoading("正在启动本地服务...");

        try
        {
            await _serverHost.RunAsync(HandleServerReadyAsync, ShowLoading, _shutdown.Token);
        }
        catch (OperationCanceledException) when (_shutdown.IsCancellationRequested)
        {
        }
        catch (Exception error)
        {
            ShowError(error.Message, error is WebView2RuntimeNotFoundException);
        }
        finally
        {
            _hostRunning = false;
        }
    }

    private async Task HandleServerReadyAsync(bool restarting)
    {
        ShowLoading(restarting ? "服务已重启，正在恢复页面..." : "正在载入应用...");
        await EnsureWebViewAsync();

        if (restarting && _webView.CoreWebView2 is not null)
        {
            _webView.CoreWebView2.Reload();
        }
        else
        {
            _webView.Source = _serverHost.AppUri;
        }

        _statusPanel.Visible = false;
        _webView.Visible = true;
        _webView.Focus();
    }

    private async Task EnsureWebViewAsync()
    {
        if (_webViewInitialized)
        {
            return;
        }

        _ = CoreWebView2Environment.GetAvailableBrowserVersionString();
        Directory.CreateDirectory(_serverHost.WebViewDataDirectory);
        var environment = await CoreWebView2Environment.CreateAsync(
            browserExecutableFolder: null,
            userDataFolder: _serverHost.WebViewDataDirectory
        );
        await _webView.EnsureCoreWebView2Async(environment);

        var core = _webView.CoreWebView2;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDevToolsEnabled = Debugger.IsAttached;
        core.Settings.IsZoomControlEnabled = true;
        core.NavigationStarting += OnNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.PermissionRequested += OnPermissionRequested;
        _webViewInitialized = true;
    }

    private void OnNavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs args)
    {
        if (args.Uri == "about:blank" || IsTrustedLocalUri(args.Uri))
        {
            return;
        }

        args.Cancel = true;
        OpenPath(args.Uri);
    }

    private void OnNewWindowRequested(object? sender, CoreWebView2NewWindowRequestedEventArgs args)
    {
        args.Handled = true;
        if (IsTrustedLocalUri(args.Uri))
        {
            _webView.CoreWebView2.Navigate(args.Uri);
        }
        else
        {
            OpenPath(args.Uri);
        }
    }

    private void OnPermissionRequested(object? sender, CoreWebView2PermissionRequestedEventArgs args)
    {
        if (args.PermissionKind == CoreWebView2PermissionKind.Microphone && IsTrustedLocalUri(args.Uri))
        {
            args.State = CoreWebView2PermissionState.Allow;
        }
    }

    private bool IsTrustedLocalUri(string value)
    {
        return Uri.TryCreate(value, UriKind.Absolute, out var uri)
            && uri.Scheme == Uri.UriSchemeHttp
            && uri.Host == "127.0.0.1"
            && uri.Port == _serverHost.Port;
    }

    private void ShowLoading(string message)
    {
        _statusLabel.Text = message;
        _progress.Visible = true;
        _retryButton.Visible = false;
        _openLogButton.Visible = false;
        _runtimeButton.Visible = false;
        _statusPanel.Visible = true;
        _statusPanel.BringToFront();
    }

    private void ShowError(string message, bool runtimeMissing)
    {
        _statusLabel.Text = message;
        _progress.Visible = false;
        _retryButton.Visible = true;
        _openLogButton.Visible = !runtimeMissing;
        _runtimeButton.Visible = runtimeMissing;
        _statusPanel.Visible = true;
        _statusPanel.BringToFront();
    }

    private static void OpenPath(string pathOrUrl)
    {
        try
        {
            Process.Start(new ProcessStartInfo(pathOrUrl) { UseShellExecute = true });
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "无法打开", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs args)
    {
        _shutdown.Cancel();
        _serverHost.Stop();
    }
}
