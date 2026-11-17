using System;
using System.Security.Principal;
using System.Threading;

internal sealed class InstallLock : IDisposable
{
    private readonly Mutex mutex;
    private InstallLock(Mutex value) { mutex = value; }
    internal static InstallLock Acquire()
    {
        string user = WindowsIdentity.GetCurrent().User.Value;
        Mutex value = new Mutex(false, @"Local\S.PDF-install-" + user);
        bool acquired = false;
        try { acquired = value.WaitOne(90000); }
        catch (AbandonedMutexException) { acquired = true; }
        if (!acquired) { value.Dispose(); throw new TimeoutException("S.PDF 설치가 끝난 뒤 다시 실행해주세요."); }
        return new InstallLock(value);
    }
    public void Dispose() { mutex.ReleaseMutex(); mutex.Dispose(); }
}
