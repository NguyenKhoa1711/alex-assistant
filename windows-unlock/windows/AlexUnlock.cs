// Windows validates the PIN. This service only targets an already locked console.
// No credential provider, password storage, network listener or arbitrary commands.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Automation;

internal static class AlexUnlock {
    internal const string PipeName = "Alex.Unlock.v1";
    static readonly string DirectoryPath = AppDomain.CurrentDomain.BaseDirectory;
    static string UserSid { get { return File.ReadAllText(Path.Combine(DirectoryPath, "user.sid")).Trim(); } }
    static readonly object AttemptLock = new object();
    static readonly List<string> StageHistory = new List<string>();
    [STAThread] static int Main(string[] args) {
        try {
            if (args.Length == 1 && args[0] == "--self-test") return SelfTest();
            if (args.Length == 1 && args[0] == "--status") {
                // Read-only; never sends keys or locks the PC.
                Console.WriteLine(ConsoleState()); return 0;
            }
            if (!WindowsIdentity.GetCurrent().IsSystem) return 2;
            if (args.Length == 2 && args[0] == "--helper" && args[1].StartsWith("Alex.Unlock.Child."))
                return Helper(args[1],false);
            if (args.Length == 2 && args[0] == "--inspect" && args[1].StartsWith("Alex.Unlock.Child."))
                return Helper(args[1],true);
            if (args.Length == 2 && args[0] == "--prepare" && args[1].StartsWith("Alex.Unlock.Child."))
                return Helper(args[1],false,true);
            if (args.Length != 0) return 2;
            ServiceBase.Run(new UnlockService()); return 0;
        } catch { return 3; } // Never write exception data containing an input buffer.
    }

    sealed class UnlockService : ServiceBase {
        volatile bool stopping;
        NamedPipeServerStream active;
        public UnlockService() { ServiceName = "AlexUnlock"; AutoLog = false; }
        protected override void OnStart(string[] args) {
            var sid = new SecurityIdentifier(UserSid); // Fail start on invalid installation.
            EnablePrivilege("SeTcbPrivilege");
            var thread = new Thread(() => Run(sid)); thread.IsBackground = true; thread.Start();
        }
        protected override void OnStop() { stopping = true; if (active != null) active.Dispose(); }
        void Run(SecurityIdentifier sid) {
            while (!stopping) {
                try {
                    using (var pipe = NewPipe(PipeName, sid)) {
                        active = pipe; pipe.WaitForConnection();
                        // Read and answer inside a bounded operation, so an abandoned pipe cannot hold the service.
                        var task = Task.Run(() => AuthenticateAndHandle(pipe, sid));
                        if (!task.Wait(25000)) pipe.Dispose();
                    }
                } catch { if (!stopping) Thread.Sleep(100); }
                finally { active = null; }
            }
        }
    }

    static string ReadPeerIdentity(NamedPipeServerStream pipe, out int opcode) {
        // ImpersonateNamedPipeClient uses the security context of the last message READ.
        // Read only the operation byte first, never a PIN, then identify the local client.
        opcode=pipe.ReadByte();
        if(opcode<0) throw new EndOfStreamException();
        string sid="";
        pipe.RunAsClient(()=>{sid=WindowsIdentity.GetCurrent().User.Value;});
        return sid;
    }
    static void AuthenticateAndHandle(NamedPipeServerStream pipe, SecurityIdentifier sid) {
        int opcode; uint session;
        string clientSid=ReadPeerIdentity(pipe,out opcode);
        if(clientSid!=sid.Value || !Native.GetNamedPipeClientSessionId(pipe.SafePipeHandle.DangerousGetHandle(),out session)
            || session!=Native.WTSGetActiveConsoleSessionId() || !ConsoleUserMatches(sid.Value,session)) return;
        Handle(pipe,session,opcode);
    }

    static NamedPipeServerStream NewPipe(string name, SecurityIdentifier sid) {
        var acl = new PipeSecurity(); acl.SetAccessRuleProtection(true, false);
        acl.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.NetworkSid, null), PipeAccessRights.FullControl, AccessControlType.Deny));
        acl.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        if (sid != null) acl.AddAccessRule(new PipeAccessRule(sid, PipeAccessRights.ReadWrite, AccessControlType.Allow));
        return new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous, 1024, 1024, acl);
    }

    static bool ConsoleUserMatches(string sid, uint session) {
        IntPtr token;
        if (!Native.WTSQueryUserToken(session, out token)) return false;
        try { using (var user = new WindowsIdentity(token)) return user.User.Value == sid; }
        finally { Native.CloseHandle(token); }
    }
    static bool ValidPin(byte[] pin) { return pin != null && pin.Length >= 4 && pin.Length <= 20 && pin.All(b => b >= 48 && b <= 57); }
    static byte[] ReadPin(Stream pipe) {
        int length = pipe.ReadByte(); if (length < 4 || length > 20) throw new InvalidDataException();
        byte[] pin = new byte[length];
        try {
            for (int i=0; i<length; i++) { int b=pipe.ReadByte(); if (b<0) throw new EndOfStreamException(); pin[i]=(byte)b; }
            if (!ValidPin(pin)) throw new InvalidDataException(); return pin;
        } catch { Array.Clear(pin,0,pin.Length); throw; }
    }
    static void Reply(Stream pipe, string code) {
        var bytes=Encoding.ASCII.GetBytes(code+"\n"); pipe.Write(bytes,0,bytes.Length); pipe.Flush();
    }
    static void Handle(NamedPipeServerStream pipe, uint session, int op) {
        byte[] pin = null;
        try {
            if (op == 0) { Reply(pipe, ConsoleState()); return; }
            // Local authenticated diagnostics only: no PIN frame, key, value write or button invocation.
            if (op == 2) {
                Reply(pipe, ConsoleState()=="locked" ? LaunchHelper(session,null) : "not_locked");
                return;
            }
            // Local authenticated preparation test: a fixed curtain key only, no
            // PIN frame. Same console/SID authorization and persistent rate limit.
            if (op == 3) {
                Reply(pipe, PrepareOnly(ConsoleState,ReserveAttempt,()=>LaunchHelper(session,null,true)));
                return;
            }
            if (op != 1) { Reply(pipe,"invalid_request"); return; }
            pin=ReadPin(pipe);
            if (ConsoleState() != "locked") { Reply(pipe,"not_locked"); return; }
            if (!ReserveAttempt()) { Reply(pipe,"rate_limited"); return; }
            // The clock curtain can be on Default, while the credential field is on
            // Winlogon. The preparation process receives NO credential bytes.
            string result=PrepareThenDeliver(()=>LaunchHelper(session,null,true),()=>LaunchHelper(session,pin));
            // Fixed status code only. Never record PIN, UI text, exception message or request bytes.
            try { File.WriteAllText(Path.Combine(DirectoryPath,"last-result.txt"),DateTime.UtcNow.ToString("o")+" "+SafeHelperResult(result,false)); } catch {}
            Reply(pipe,result);
        } catch { try { Reply(pipe,"unknown_result"); } catch {} }
        finally { if (pin != null) Array.Clear(pin,0,pin.Length); }
    }
    static bool ReserveAttempt() {
        lock (AttemptLock) {
            // Protected installation directory. Persist before typing; restart cannot reset the limit.
            try {
                string path=Path.Combine(DirectoryPath,"attempts.txt"); long now=DateTime.UtcNow.Ticks;
                var recent=new List<long>();
                if(File.Exists(path)) foreach(string line in File.ReadAllLines(path)) {
                    long t; if(!long.TryParse(line,out t)) return false;
                    if(now-t < TimeSpan.FromMinutes(1).Ticks) recent.Add(t);
                }
                if(recent.Count>=3) return false;
                recent.Add(now); File.WriteAllLines(path,recent.Select(t=>t.ToString()).ToArray()); return true;
            } catch { return false; }
        }
    }
    static string ConsoleState() {
        uint session=Native.WTSGetActiveConsoleSessionId(); IntPtr buffer; int bytes;
        if(session==0xffffffff || !Native.WTSQuerySessionInformation(IntPtr.Zero,session,25,out buffer,out bytes)) return "unavailable";
        try {
            if(bytes < Marshal.SizeOf(typeof(Native.WTSINFOEX))) return "unavailable";
            var info=(Native.WTSINFOEX)Marshal.PtrToStructure(buffer,typeof(Native.WTSINFOEX));
            if(info.Level != 1 || info.Data.SessionId != session || info.Data.SessionState != 0) return "unavailable";
            return info.Data.SessionFlags == 0 ? "locked" : info.Data.SessionFlags == 1 ? "unlocked" : "unavailable";
        } finally { Native.WTSFreeMemory(buffer); }
    }

    static string PrepareThenDeliver(Func<string> prepare,Func<string> deliver) {
        string ready=prepare();
        return ready=="pin_desktop_ready" ? deliver() : ready;
    }
    static string PrepareOnly(Func<string> state,Func<bool> reserve,Func<string> prepare) {
        if(state()!="locked") return "not_locked";
        if(!reserve()) return "rate_limited";
        return SafePreparationResult(prepare());
    }
    static string LaunchHelper(uint session, byte[] pin,bool prepare=false) {
        bool inspect=pin==null && !prepare;
        string name="Alex.Unlock.Child."+Guid.NewGuid().ToString("N");
        using(var pipe=NewPipe(name,null)) {
            var wait=pipe.BeginWaitForConnection(null,null);
            IntPtr original=IntPtr.Zero, token=IntPtr.Zero;
            Native.PROCESS_INFORMATION proc=new Native.PROCESS_INFORMATION();
            try {
                EnablePrivilege("SeTcbPrivilege");
                if(!Native.OpenProcessToken(Native.GetCurrentProcess(),0x000a,out original)
                    || !Native.DuplicateTokenEx(original,0xF01FF,IntPtr.Zero,2,1,out token)
                    || !Native.SetTokenInformation(token,12,ref session,4)) return "helper_unavailable";
                var si=new Native.STARTUPINFO(); si.cb=Marshal.SizeOf(si); si.lpDesktop="winsta0\\Winlogon";
                string exe=Path.Combine(DirectoryPath,"AlexUnlock.exe");
                if(!Native.CreateProcessAsUser(token,exe,new StringBuilder("\""+exe+"\" "+(prepare?"--prepare ":inspect?"--inspect ":"--helper ")+name),IntPtr.Zero,IntPtr.Zero,false,
                    0x08000000,IntPtr.Zero,DirectoryPath,ref si,out proc)) return "helper_unavailable";
                if(!wait.AsyncWaitHandle.WaitOne(5000)) return "helper_unavailable";
                pipe.EndWaitForConnection(wait); uint pid;
                if(!Native.GetNamedPipeClientProcessId(pipe.SafePipeHandle.DangerousGetHandle(),out pid) || pid!=proc.dwProcessId) return "helper_unavailable";
                if(prepare) pipe.WriteByte(3);
                else if(inspect) pipe.WriteByte(2);
                else { pipe.WriteByte((byte)pin.Length); pipe.Write(pin,0,pin.Length); }
                pipe.Flush();
                var response=Task.Run(()=> {
                    var data=new List<byte>(); int b;
                    while(data.Count<64 && (b=pipe.ReadByte())>=0 && b!=10) data.Add((byte)b);
                    string code=Encoding.ASCII.GetString(data.ToArray());
                    return prepare ? SafePreparationResult(code) : SafeHelperResult(code,inspect);
                });
                return response.Wait(16000) ? response.Result : "unknown_result";
            } finally {
                if(proc.hProcess!=IntPtr.Zero) {
                    if(Native.WaitForSingleObject(proc.hProcess,100)!=0) Native.TerminateProcess(proc.hProcess,1);
                    Native.CloseHandle(proc.hProcess); Native.CloseHandle(proc.hThread);
                }
                if(token!=IntPtr.Zero) Native.CloseHandle(token); if(original!=IntPtr.Zero) Native.CloseHandle(original);
                wait.AsyncWaitHandle.Close();
            }
        }
    }
    static string SafePreparationResult(string code) {
        return new[]{"pin_desktop_ready","not_locked","pin_field_unavailable","helper_unavailable"}.Contains(code) ? code : "unknown_result";
    }
    static string SafeHelperResult(string code,bool inspect) {
        var normal=new[]{"unlocked","pin_field_unavailable","not_locked","unknown_result","helper_unavailable"};
        var diagnostic=new[]{"diag_console","diag_desktop","diag_lock_curtain","diag_foreground",
            "diag_pin_missing","diag_value_missing","diag_readonly","diag_submit_missing","diag_submit_pending",
            "diag_invoke_missing","diag_ready","diag_error","diag_default_lock_curtain",
            "diag_input_unavailable","diag_input_unsupported","diag_attach_failed","not_locked","helper_unavailable"};
        return (inspect?diagnostic:normal).Contains(code)?code:"unknown_result";
    }
    static void DiagnosticStage(string stage,int error=0) {
        // Call sites supply constant stage identifiers and HRESULT numbers only.
        if(!System.Text.RegularExpressions.Regex.IsMatch(stage??"",@"\A[a-z_]{1,40}\z")) return;
        string row=DateTime.UtcNow.ToString("o")+" "+stage+" hresult="+error.ToString("X8");
        lock(StageHistory) { if(StageHistory.Count>=32) StageHistory.RemoveAt(0); StageHistory.Add(row); }
        try { File.WriteAllText(Path.Combine(DirectoryPath,"last-stage.txt"),row); } catch {}
    }
    static void SavePreparationTrace() {
        // Fixed stage codes and error numbers only, bounded to this helper run.
        try { lock(StageHistory) File.WriteAllLines(Path.Combine(DirectoryPath,"last-preparation.txt"),StageHistory.ToArray()); } catch {}
    }
    static void InspectButtonCapabilities(AutomationElement field) {
        // Do not read Name, Value or text patterns. AutomationId identifies controls,
        // not their contents; only inspect buttons in the already verified LogonUI.
        try {
            if(!TargetMatches(field)) return;
            uint pid; Native.GetWindowThreadProcessId(Native.GetForegroundWindow(),out pid);
            var root=AutomationElement.FromHandle(Native.GetForegroundWindow());
            var nodes=root.FindAll(TreeScope.Descendants,new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Button));
            var rows=new List<string>();
            foreach(AutomationElement node in nodes) {
                if(rows.Count>=16) break;
                var c=node.Current; if(c.ProcessId!=(int)pid) continue;
                string id=c.AutomationId??"";
                if(!System.Text.RegularExpressions.Regex.IsMatch(id,@"\A[A-Za-z0-9_.-]{0,80}\z")) id="redacted";
                object pattern;
                rows.Add("id="+id+";enabled="+c.IsEnabled+";offscreen="+c.IsOffscreen+";invoke="+node.TryGetCurrentPattern(InvokePattern.Pattern,out pattern));
            }
            File.WriteAllLines(Path.Combine(DirectoryPath,"button-capabilities.txt"),rows.ToArray());
        } catch { DiagnosticStage("inspect_buttons_error"); }
    }
    static void EnablePrivilege(string name) {
        IntPtr token; if(!Native.OpenProcessToken(Native.GetCurrentProcess(),0x28,out token)) throw new InvalidOperationException();
        try {
            var p=new Native.TOKEN_PRIVILEGES(); p.Count=1; p.Attributes=2;
            if(!Native.LookupPrivilegeValue(null,name,out p.Luid) || !Native.AdjustTokenPrivileges(token,false,ref p,0,IntPtr.Zero,IntPtr.Zero)
                || Marshal.GetLastWin32Error()!=0) throw new InvalidOperationException();
        } finally { Native.CloseHandle(token); }
    }
    static int Helper(string name,bool inspect,bool prepare=false) {
        using(var pipe=new NamedPipeClientStream(".",name,PipeDirection.InOut)) {
            pipe.Connect(5000); byte[] pin=null;
            try {
                if(prepare) {
                    if(pipe.ReadByte()!=3) return 2;
                    string result=OnInputDesktop(PreparePinDesktop,true);
                    SavePreparationTrace(); Reply(pipe,result);
                }
                else if(inspect) {
                    if(pipe.ReadByte()!=2) return 2;
                    Reply(pipe,OnInputDesktop(InspectTarget));
                }
                else { pin=ReadPin(pipe); Reply(pipe,TypeIntoVerifiedPin(pin)); }
            }
            catch(Exception error) {
                DiagnosticStage("helper_failed",error.HResult); if(prepare) SavePreparationTrace();
                try { Reply(pipe,"unknown_result"); } catch {}
            }
            finally { if(pin!=null) Array.Clear(pin,0,pin.Length); }
        }
        return 0;
    }
    static string InputDesktopName() {
        IntPtr desktop=Native.OpenInputDesktop(0,false,1); if(desktop==IntPtr.Zero) return "";
        try { return DesktopName(desktop); }
        finally { Native.CloseDesktop(desktop); }
    }
    static string DesktopName(IntPtr desktop) {
        var name=new StringBuilder(64); uint needed;
        return Native.GetUserObjectInformation(desktop,2,name,128,out needed) ? name.ToString() : "";
    }
    static string AttachInputDesktop(bool allowFixedInput) {
        // Only the disposable no-PIN preparation/inspection process calls this,
        // before creating any UIA object. Never switch the user's visible desktop.
        // READOBJECTS | WRITEOBJECTS; preparation also needs JOURNALPLAYBACK
        // for SendInput. Without 0x20 Windows accepts attachment but rejects keys
        // with ERROR_ACCESS_DENIED. This changes handle rights, never the ACL.
        IntPtr desktop=Native.OpenInputDesktop(0,false,allowFixedInput?0xA1u:0x81u);
        if(desktop==IntPtr.Zero) { DiagnosticStage("diag_input_unavailable",Marshal.GetLastWin32Error()); return "diag_input_unavailable"; }
        string name=DesktopName(desktop);
        if(name!="Default" && name!="Winlogon") { Native.CloseDesktop(desktop); return "diag_input_unsupported"; }
        if(!Native.SetThreadDesktop(desktop)) {
            int error=Marshal.GetLastWin32Error(); Native.CloseDesktop(desktop);
            DiagnosticStage("diag_attach_failed",error); return "diag_attach_failed";
        }
        // This handle is assigned to the thread. The short-lived helper process
        // owns it until exit (CloseDesktop cannot close an assigned desktop).
        return "attached";
    }
    static string OnInputDesktop(Func<string> operation,bool allowFixedInput=false) {
        // A fresh MTA thread has no STA/COM message window or hook. Windows refuses
        // SetThreadDesktop on a thread which already owns such a window (ERROR_BUSY).
        // Call sites are only preparation/inspection; no PIN is passed to this thread.
        string result="unknown_result";
        var thread=new Thread(()=> {
            try {
                if(!HelperOwnsConsole() || ConsoleState()!="locked") { result="not_locked"; return; }
                DiagnosticStage("input_desktop_attach_begin");
                string attached=AttachInputDesktop(allowFixedInput);
                if(attached=="attached") DiagnosticStage("input_desktop_attached");
                result=attached=="attached" ? operation() : attached;
            } catch(Exception error) { DiagnosticStage("input_desktop_operation_failed",error.HResult); result="unknown_result"; }
        });
        thread.IsBackground=true; thread.SetApartmentState(ApartmentState.MTA);
        thread.Start();
        return thread.Join(7000) ? result : "unknown_result";
    }
    static string PreparePinDesktop() {
        DiagnosticStage("prepare_started");
        if(!HelperOwnsConsole() || ConsoleState()!="locked") return "not_locked";
        DismissLockCurtain();
        for(int i=0;i<30;i++) {
            if(!HelperOwnsConsole() || ConsoleState()!="locked") return "not_locked";
            if(InputDesktopName()=="Winlogon") { DiagnosticStage("pin_desktop_ready"); return "pin_desktop_ready"; }
            Thread.Sleep(100);
        }
        DiagnosticStage("curtain_still_active"); return "pin_field_unavailable";
    }
    static bool SystemForeground(string expected) {
        uint pid; Native.GetWindowThreadProcessId(Native.GetForegroundWindow(),out pid);
        try {
            using(var p=Process.GetProcessById((int)pid)) {
                // Validate executable path as well as name, not a user-controlled window title.
                string path=p.MainModule.FileName;
                string win=Environment.GetFolderPath(Environment.SpecialFolder.Windows);
                if(expected=="LogonUI") return path.Equals(Path.Combine(win,"System32\\LogonUI.exe"),StringComparison.OrdinalIgnoreCase);
                return p.ProcessName=="LockApp" && path.StartsWith(Path.Combine(win,"SystemApps")+"\\",StringComparison.OrdinalIgnoreCase);
            }
        } catch { return false; }
    }
    static AutomationElement PinField() {
        if(InputDesktopName()!="Winlogon" || !SystemForeground("LogonUI") || ConsoleState()!="locked") return null;
        uint pid; Native.GetWindowThreadProcessId(Native.GetForegroundWindow(),out pid);
        var root=AutomationElement.FromHandle(Native.GetForegroundWindow());
        var nodes=root.FindAll(TreeScope.Descendants,new AndCondition(
            new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Edit),
            new PropertyCondition(AutomationElement.IsPasswordProperty,true)));
        AutomationElement result=null;
        foreach(AutomationElement node in nodes) {
            var c=node.Current;
            if(c.ProcessId!=(int)pid || !c.IsEnabled || c.IsOffscreen || !IsPinName(c.Name)) continue;
            if(result!=null) return null; result=node;
        }
        return result;
    }
    static bool IsPinName(string name) {
        // Deliberately narrow: never type a Hello PIN into a password, MFA or app field.
        return System.Text.RegularExpressions.Regex.IsMatch(name ?? "", @"\bPIN\b",System.Text.RegularExpressions.RegexOptions.IgnoreCase);
    }
    static string InspectTarget() {
        try {
            if(!HelperOwnsConsole()) return "diag_console";
            if(ConsoleState()!="locked") return "not_locked";
            if(InputDesktopName()=="Default" && SystemForeground("LockApp")) return "diag_default_lock_curtain";
            if(InputDesktopName()!="Winlogon") return "diag_desktop";
            if(SystemForeground("LockApp")) return "diag_lock_curtain";
            if(!SystemForeground("LogonUI")) return "diag_foreground";
            var field=PinField(); if(field==null) return "diag_pin_missing";
            InspectButtonCapabilities(field);
            object value,invoke;
            if(!field.TryGetCurrentPattern(ValuePattern.Pattern,out value)) return "diag_value_missing";
            if(((ValuePattern)value).Current.IsReadOnly) return "diag_readonly";
            var button=SubmitButton(field,false); if(button==null) return "diag_submit_missing";
            if(!button.Current.IsEnabled || button.Current.IsOffscreen) return "diag_submit_pending";
            if(!button.TryGetCurrentPattern(InvokePattern.Pattern,out invoke)) return "diag_invoke_missing";
            return "diag_ready";
        } catch { return "diag_error"; }
    }
    static bool TargetMatches(AutomationElement expected) {
        if(!HelperOwnsConsole() || InputDesktopName()!="Winlogon" || !SystemForeground("LogonUI") || ConsoleState()!="locked") return false;
        var actual=PinField();
        return actual!=null && Automation.Compare(expected,actual);
    }
    static AutomationElement SubmitButton(AutomationElement field,bool requireInteractive=true) {
        if(!TargetMatches(field)) return null;
        uint pid; Native.GetWindowThreadProcessId(Native.GetForegroundWindow(),out pid);
        var root=AutomationElement.FromHandle(Native.GetForegroundWindow());
        var nodes=root.FindAll(TreeScope.Descendants,new AndCondition(
            new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Button),
            new PropertyCondition(AutomationElement.AutomationIdProperty,"SubmitButton")));
        AutomationElement result=null;
        foreach(AutomationElement node in nodes) {
            var c=node.Current;
            if(c.ProcessId!=(int)pid || (requireInteractive && (!c.IsEnabled || c.IsOffscreen))) continue;
            if(result!=null) return null; result=node;
        }
        return result;
    }
    static void InvokeVerifiedSubmit(AutomationElement field) {
        // Hello may create/enable its submit button only after SetValue.
        // Discover it only at submission time; never substitute Enter or an arbitrary button.
        var button=SubmitButton(field); object pattern;
        if(button==null) { DiagnosticStage("submit_missing"); throw new InvalidOperationException(); }
        if(!button.TryGetCurrentPattern(InvokePattern.Pattern,out pattern)) { DiagnosticStage("invoke_missing"); throw new InvalidOperationException(); }
        var current=SubmitButton(field);
        if(current==null || !Automation.Compare(button,current)) { DiagnosticStage("submit_target_changed"); throw new InvalidOperationException(); }
        try { ((InvokePattern)pattern).Invoke(); DiagnosticStage("submit_invoked"); }
        catch(Exception error) { DiagnosticStage("invoke_failed",error.HResult); throw; }
    }
    // A transaction bound to specific UIA objects, never to the keyboard focus.
    // Exceptions after SetValue are ambiguous: do not retry or clear another value.
    static string DeliverOnce(byte[] pin, Func<bool> verified, Action<byte[]> write,
                              Func<string> state, Action submit) {
        if(!ValidPin(pin)) return "invalid_request";
        bool started=false;
        try {
            if(!verified()) return "pin_field_unavailable";
            started=true;
            write(pin);
            if(state()=="unlocked") return "unlocked";
            if(!verified()) return "unknown_result";
            submit();
            return "submitted";
        } catch { return started ? "unknown_result" : "pin_field_unavailable"; }
    }
    static string ObserveUnlockResult(string result,Func<string> state,Action wait) {
        if(result!="submitted" && result!="unknown_result") return result;
        // Hello may unlock asynchronously after SetValue and invalidate UIA objects.
        // Observe only; never resend credentials or invoke a second submit operation.
        try {
            for(int i=0;i<40;i++) { if(state()=="unlocked") return "unlocked"; wait(); }
        } catch {}
        return "unknown_result";
    }
    static string TypeIntoVerifiedPin(byte[] pin) {
        DiagnosticStage("attempt_started");
        if(!HelperOwnsConsole() || ConsoleState()!="locked") return "not_locked";
        if(InputDesktopName()!="Winlogon") { DiagnosticStage("credential_desktop_missing"); return "pin_field_unavailable"; }
        AutomationElement field=null;
        for(int i=0;i<20 && field==null;i++) { Thread.Sleep(150); field=PinField(); }
        if(field==null) { DiagnosticStage("pin_field_missing"); return "pin_field_unavailable"; }
        object valueObject;
        if(!field.TryGetCurrentPattern(ValuePattern.Pattern,out valueObject)) { DiagnosticStage("value_pattern_missing"); return "pin_field_unavailable"; }
        var value=(ValuePattern)valueObject;
        if(value.Current.IsReadOnly) return "pin_field_unavailable";
        Func<bool> verified=()=> {
            return TargetMatches(field) && !value.Current.IsReadOnly;
        };
        var result=DeliverOnce(pin,verified,digits=> {
            // ValuePattern targets the verified password control directly. If unsupported,
            // fail closed; never fall back to SendInput/clipboard/foreground keystrokes.
            // UIA requires a managed string; its lifetime cannot be securely zeroed here.
            char[] chars=new char[digits.Length];
            try {
                for(int i=0;i<digits.Length;i++) chars[i]=(char)digits[i];
                try { value.SetValue(new string(chars)); DiagnosticStage("value_set"); }
                catch(Exception error) { DiagnosticStage("value_set_failed",error.HResult); throw; }
            } finally { Array.Clear(chars,0,chars.Length); }
        },()=>HelperOwnsConsole()?ConsoleState():"unavailable",()=>InvokeVerifiedSubmit(field));
        string final=ObserveUnlockResult(result,()=>HelperOwnsConsole()?ConsoleState():"unavailable",()=>Thread.Sleep(150));
        if(final=="unlocked") DiagnosticStage("observed_unlocked");
        return final; // Do not infer bad PIN, retry or expose Windows's private UI text.
    }
    static bool HelperOwnsConsole() {
        uint session=Native.WTSGetActiveConsoleSessionId();
        return session==(uint)Process.GetCurrentProcess().SessionId && ConsoleUserMatches(UserSid,session);
    }
    static bool ShouldDismissCurtain(bool verifiedLockedDesktop,bool trustedLockWindow,bool visibleEdit) {
        return verifiedLockedDesktop && trustedLockWindow && !visibleEdit;
    }
    static bool CurtainWindowAllowed(string desktop,bool lockApp,bool logonUi) {
        return (desktop=="Default" && lockApp) || (desktop=="Winlogon" && (lockApp || logonUi));
    }
    static void DismissLockCurtain() {
        // A single fixed Space only reveals the sign-in UI. Never send PIN digits
        // or Enter, and leave any existing PIN/password/text field untouched.
        if(!HelperOwnsConsole() || ConsoleState()!="locked") { DiagnosticStage("curtain_not_locked"); return; }
        string desktop=InputDesktopName();
        bool trusted=CurtainWindowAllowed(desktop,SystemForeground("LockApp"),SystemForeground("LogonUI"));
        if(!trusted) { DiagnosticStage("curtain_untrusted_window"); return; }
        IntPtr window=Native.GetForegroundWindow(); bool visibleEdit=false;
        try {
            var root=AutomationElement.FromHandle(window);
            var fields=root.FindAll(TreeScope.Descendants,new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Edit));
            foreach(AutomationElement field in fields) {
                if(field.Current.IsEnabled && !field.Current.IsOffscreen) { visibleEdit=true; break; }
            }
        } catch { DiagnosticStage("curtain_inspection_failed"); return; }
        bool context=HelperOwnsConsole() && ConsoleState()=="locked" && InputDesktopName()==desktop
            && Native.GetForegroundWindow()==window;
        if(!ShouldDismissCurtain(context,trusted,visibleEdit)) { DiagnosticStage(visibleEdit?"curtain_edit_visible":"curtain_context_changed"); return; }
        DiagnosticStage("curtain_space_sending");
        Native.SendKeys(new[]{Native.Input(0x20,0,0),Native.Input(0x20,0,2)});
        DiagnosticStage("curtain_space_sent");
    }
    static int SelfTest() {
        if(!ValidPin(new byte[]{49,50,51,52}) || ValidPin(new byte[]{49,50,51}) || ValidPin(new byte[]{49,50,51,0})
            || !IsPinName("Mã PIN") || IsPinName("Password") || IsPinName("spinning")
            || Marshal.SizeOf(typeof(Native.INPUT))!=40) return 1;
        Console.WriteLine("PASS: PIN validation, target labels and x64 input layout; no keys sent."); return 0;
    }

    static class Native {
        [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] internal struct WTSINFOEX_LEVEL1 {
            public uint SessionId; public int SessionState,SessionFlags;
            [MarshalAs(UnmanagedType.ByValTStr,SizeConst=33)] public string WinStationName;
            [MarshalAs(UnmanagedType.ByValTStr,SizeConst=21)] public string UserName;
            [MarshalAs(UnmanagedType.ByValTStr,SizeConst=18)] public string DomainName;
            public long LogonTime,ConnectTime,DisconnectTime,LastInputTime,CurrentTime;
            public uint IncomingBytes,OutgoingBytes,IncomingFrames,OutgoingFrames,IncomingCompressedBytes,OutgoingCompressedBytes;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct WTSINFOEX { public uint Level; public WTSINFOEX_LEVEL1 Data; }
        [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] internal struct STARTUPINFO {
            public int cb; public string lpReserved,lpDesktop,lpTitle; public int dwX,dwY,dwXSize,dwYSize,dwXCountChars,dwYCountChars,dwFillAttribute,dwFlags;
            public short wShowWindow,cbReserved2; public IntPtr lpReserved2,hStdInput,hStdOutput,hStdError;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct PROCESS_INFORMATION { public IntPtr hProcess,hThread; public uint dwProcessId,dwThreadId; }
        [StructLayout(LayoutKind.Sequential)] internal struct LUID { public uint Low; public int High; }
        [StructLayout(LayoutKind.Sequential)] internal struct TOKEN_PRIVILEGES { public uint Count; public LUID Luid; public uint Attributes; }
        [StructLayout(LayoutKind.Explicit,Size=40)] internal struct INPUT {
            [FieldOffset(0)] public uint type; [FieldOffset(8)] public ushort vk; [FieldOffset(10)] public ushort scan;
            [FieldOffset(12)] public uint flags; [FieldOffset(16)] public uint time; [FieldOffset(24)] public UIntPtr extra;
        }
        internal static INPUT Input(ushort vk,ushort scan,uint flags) { return new INPUT{type=1,vk=vk,scan=scan,flags=flags}; }
        internal static void SendKeys(INPUT[] inputs) {
            try {
                uint sent=SendInput((uint)inputs.Length,inputs,40);
                if(sent!=inputs.Length) {
                    int error=Marshal.GetLastWin32Error();
                    DiagnosticStage("curtain_input_rejected",error); throw new InvalidOperationException();
                }
            }
            finally { Array.Clear(inputs,0,inputs.Length); }
        }
        [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint n,INPUT[] inputs,int size);
        [DllImport("kernel32.dll")] internal static extern uint WTSGetActiveConsoleSessionId();
        [DllImport("wtsapi32.dll",CharSet=CharSet.Unicode,EntryPoint="WTSQuerySessionInformationW")] internal static extern bool WTSQuerySessionInformation(IntPtr server,uint session,int info,out IntPtr buffer,out int bytes);
        [DllImport("wtsapi32.dll")] internal static extern void WTSFreeMemory(IntPtr memory);
        [DllImport("wtsapi32.dll",SetLastError=true)] internal static extern bool WTSQueryUserToken(uint session,out IntPtr token);
        [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool GetNamedPipeClientSessionId(IntPtr pipe,out uint session);
        [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool GetNamedPipeClientProcessId(IntPtr pipe,out uint pid);
        [DllImport("kernel32.dll")] internal static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll")] internal static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll")] internal static extern uint WaitForSingleObject(IntPtr handle,uint ms);
        [DllImport("kernel32.dll")] internal static extern bool TerminateProcess(IntPtr process,uint code);
        [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
        [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool DuplicateTokenEx(IntPtr existing,uint access,IntPtr attrs,int level,int type,out IntPtr token);
        [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool SetTokenInformation(IntPtr token,int type,ref uint value,int size);
        [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] internal static extern bool LookupPrivilegeValue(string system,string name,out LUID value);
        [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool AdjustTokenPrivileges(IntPtr token,bool disable,ref TOKEN_PRIVILEGES p,int len,IntPtr old,IntPtr needed);
        [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] internal static extern bool CreateProcessAsUser(IntPtr token,string app,StringBuilder command,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string dir,ref STARTUPINFO si,out PROCESS_INFORMATION pi);
        [DllImport("user32.dll",SetLastError=true)] internal static extern IntPtr OpenInputDesktop(uint flags,bool inherit,uint access);
        [DllImport("user32.dll",CharSet=CharSet.Unicode,EntryPoint="GetUserObjectInformationW")] internal static extern bool GetUserObjectInformation(IntPtr obj,int index,StringBuilder name,uint length,out uint needed);
        [DllImport("user32.dll")] internal static extern bool CloseDesktop(IntPtr desktop);
        [DllImport("user32.dll",SetLastError=true)] internal static extern bool SetThreadDesktop(IntPtr desktop);
        [DllImport("user32.dll")] internal static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] internal static extern uint GetWindowThreadProcessId(IntPtr window,out uint pid);
    }
}
