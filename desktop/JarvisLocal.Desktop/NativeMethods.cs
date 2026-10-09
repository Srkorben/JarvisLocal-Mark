using System.Runtime.InteropServices;

namespace JarvisLocal.Desktop;

internal static class NativeMethods
{
    internal static readonly uint ActivateMessage =
        RegisterWindowMessage("JarvisLocal.Desktop.Activate.v1");

    private static readonly nint BroadcastHandle = new(0xffff);

    internal static void BroadcastActivate() =>
        PostMessage(BroadcastHandle, ActivateMessage, nint.Zero, nint.Zero);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern uint RegisterWindowMessage(string lpString);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool PostMessage(nint hWnd, uint msg, nint wParam, nint lParam);
}
