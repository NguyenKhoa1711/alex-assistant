using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Principal;
using System.Text.RegularExpressions;
using System.Threading;

// No network, credentials, arbitrary commands, or user-provided executable paths.
// The scheduled task runs this protected binary only for one temporary display lease.
static class DisplayPriority {
    static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    static readonly string LeasePath = Path.Combine(Root,"active.json");
    static readonly string StatusPath = Path.Combine(Root,"status.txt");
    static readonly Guid Video = new Guid("7516b95f-f776-4464-8c53-06167f40cc99");
    static readonly Guid LockTimeout = new Guid("8ec4b3a5-6868-48c2-be75-4f3044be88a7");
    static string RequestPath;
    static string Ticket = "-";

    [DataContract] sealed class Lease {
        [DataMember] public string Ticket;
        [DataMember] public string Scheme;
        [DataMember] public uint Timeout;
        [DataMember] public string Before;
        [DataMember] public int Pid;
        [DataMember] public long ProcessStart;
    }

    static int Main(string[] args) {
        if(args.Length==1 && args[0]=="--self-test") return SelfTest();
        if(args.Length!=1 || (args[0]!="--run" && args[0]!="--restore")) return 2;
        if(!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) return 3;
        var settings=File.ReadAllLines(Path.Combine(Root,"settings.txt"));
        if(settings.Length!=2 || WindowsIdentity.GetCurrent().User.Value!=settings[0]) return 4;
        RequestPath=settings[1];
        // File lock in the admin-owned install directory cannot be precreated by a normal user.
        FileStream guard;
        try { guard=new FileStream(Path.Combine(Root,"worker.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None); }
        catch(IOException) { Diagnostic("worker_busy"); return 0; }
        using(guard) {
            try {
                if(File.Exists(LeasePath)) Restore(); // crash/logon/unlock recovery
                if(args[0]=="--restore") { Status("restored"); return 0; }
                int pid; long issued; string ticket;
                if(!ReadRequest(out ticket,out issued,out pid)) return 0;
                Ticket=ticket;
                string consumed=Path.Combine(Root,"last-ticket.txt");
                if(File.Exists(consumed) && File.ReadAllText(consumed)==ticket) { Diagnostic("already_consumed"); return 0; }
                Process owner=Process.GetProcessById(pid);
                long processStart=owner.StartTime.ToUniversalTime().Ticks;
                if(owner.SessionId!=Process.GetCurrentProcess().SessionId || ConsoleState()=="unavailable") return 5;
                File.WriteAllText(consumed,ticket);
                Status("armed");
                var deadline=DateTime.UtcNow.AddSeconds(12);
                while(ConsoleState()!="locked") {
                    if(DateTime.UtcNow>deadline || !RequestMatches(ticket) || !OwnerAlive(pid,processStart)) {
                        Status("cancelled"); return 0;
                    }
                    Thread.Sleep(100);
                }
                if(!RequestMatches(ticket) || !OwnerAlive(pid,processStart)) { Status("cancelled"); return 0; }
                string before=GetOverride();
                if(before.Split(' ').Contains("DISPLAY")) throw new InvalidOperationException("Existing display override is not ours.");
                Guid scheme=ActiveScheme();
                var lease=new Lease {Ticket=ticket,Scheme=scheme.ToString(),Timeout=ReadTimeout(scheme),Before=before,Pid=pid,ProcessStart=processStart};
                WriteLease(lease); // journal before changing either setting
                SetOverride(AddDisplay(before));
                SetTimeout(scheme,2);
                Status("active");
                // Unlock, client exit/cancel, or unknown session releases only our changes.
                while(ConsoleState()=="locked" && OwnerAlive(pid,processStart) && RequestMatches(ticket)) Thread.Sleep(250);
                Restore();
                Status("restored");
                return 0;
            } catch(Exception e) {
                try { if(File.Exists(LeasePath)) Restore(); } catch { Status("restore_failed"); return 7; }
                Status("error_"+e.GetType().Name); return 6;
            }
        }
    }

    static bool ParseRequest(string text,long now,out string ticket,out long issued,out int pid) {
        ticket=null; issued=0; pid=0;
        if(text.Length>128) return false;
        string[] p=text.Trim().Split('|');
        if(p.Length!=3 || !Regex.IsMatch(p[0],"^[a-f0-9]{32}$") || !long.TryParse(p[1],out issued) || !int.TryParse(p[2],out pid)) return false;
        if(pid<=0 || issued<now-15000 || issued>now+3000) return false;
        ticket=p[0]; return true;
    }
    static string RequestText() {
        using(var f=new FileStream(RequestPath,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)) {
            if(f.Length>128) throw new InvalidDataException();
            using(var r=new StreamReader(f)) return r.ReadToEnd();
        }
    }
    static bool ReadRequest(out string ticket,out long issued,out int pid) {
        ticket=null; issued=0; pid=0;
        try {
            bool valid=ParseRequest(RequestText(),(long)(DateTime.UtcNow-new DateTime(1970,1,1)).TotalMilliseconds,out ticket,out issued,out pid);
            if(!valid) Diagnostic("request_invalid_or_expired");
            return valid;
        }
        catch(Exception e) { Diagnostic("request_read_"+e.GetType().Name+"_"+e.HResult); return false; }
    }
    static bool RequestMatches(string ticket) {
        try { return RequestText().StartsWith(ticket+"|",StringComparison.Ordinal); } catch { return false; }
    }
    static bool OwnerAlive(int pid,long start) {
        try { using(var p=Process.GetProcessById(pid)) return !p.HasExited && p.StartTime.ToUniversalTime().Ticks==start; } catch { return false; }
    }
    static void Status(string status) {
        Diagnostic(status);
        string temp=StatusPath+".tmp";
        File.WriteAllText(temp,Ticket+"|"+status+"|"+DateTime.UtcNow.ToString("o"));
        if(File.Exists(StatusPath)) File.Replace(temp,StatusPath,null); else File.Move(temp,StatusPath);
    }
    static void Diagnostic(string state) {
        try { File.WriteAllText(Path.Combine(Root,"diagnostic.txt"),DateTime.UtcNow.ToString("o")+"|"+state); } catch {}
    }
    static void WriteLease(Lease lease) {
        using(var f=new FileStream(LeasePath,FileMode.Create,FileAccess.Write,FileShare.None)) new DataContractJsonSerializer(typeof(Lease)).WriteObject(f,lease);
    }
    static void Restore() {
        Lease lease;
        using(var f=File.OpenRead(LeasePath)) lease=(Lease)new DataContractJsonSerializer(typeof(Lease)).ReadObject(f);
        Ticket=lease.Ticket;
        string current=GetOverride();
        string expected=AddDisplay(lease.Before);
        // Never erase a concurrent administrator's unrelated override.
        if(current==expected) SetOverride(lease.Before);
        else if(current!=lease.Before) throw new InvalidOperationException("Concurrent display policy change.");
        Guid scheme=Guid.Parse(lease.Scheme);
        uint value=ReadTimeout(scheme);
        if(value==2) SetTimeout(scheme,lease.Timeout);
        else if(value!=lease.Timeout) throw new InvalidOperationException("Concurrent timeout change.");
        File.Delete(LeasePath);
    }
    static string Normalize(string tokens) {
        var words=tokens.Split(new[]{' ','\t'},StringSplitOptions.RemoveEmptyEntries).Select(s=>s.ToUpperInvariant()).Distinct().OrderBy(s=>s).ToArray();
        if(words.Any(s=>s!="DISPLAY" && s!="SYSTEM" && s!="AWAYMODE")) throw new InvalidDataException();
        return string.Join(" ",words);
    }
    static string AddDisplay(string before) { return Normalize(before+" DISPLAY"); }
    static string PowerCfg(string args) {
        var info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"powercfg.exe"),args) {
            UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true
        };
        using(var p=Process.Start(info)) {
            var output=p.StandardOutput.ReadToEndAsync(); var error=p.StandardError.ReadToEndAsync();
            if(!p.WaitForExit(5000)) { p.Kill(); throw new TimeoutException(); }
            if(p.ExitCode!=0) throw new InvalidOperationException("Power policy command failed.");
            return output.Result;
        }
    }
    static string GetOverride() {
        return ParseOverride(PowerCfg("/requestsoverride"));
    }
    static string ParseOverride(string text) {
        bool process=false;
        foreach(string raw in text.Split('\n')) {
            string line=raw.Trim();
            if(line.StartsWith("[")) { process=line.Equals("[PROCESS]",StringComparison.OrdinalIgnoreCase); continue; }
            if(process) {
                var match=Regex.Match(line,@"^Antigravity\.exe\s+(.*)$",RegexOptions.IgnoreCase);
                if(match.Success) return Normalize(match.Groups[1].Value);
            }
        }
        return "";
    }
    static void SetOverride(string value) { PowerCfg("/requestsoverride PROCESS Antigravity.exe"+(value.Length==0?"":" "+Normalize(value))); }
    static Guid ActiveScheme() {
        IntPtr p; if(PowerGetActiveScheme(IntPtr.Zero,out p)!=0) throw new InvalidOperationException();
        try { return (Guid)Marshal.PtrToStructure(p,typeof(Guid)); } finally { LocalFree(p); }
    }
    static uint ReadTimeout(Guid scheme) {
        Guid video=Video, setting=LockTimeout; uint value;
        if(PowerReadACValueIndex(IntPtr.Zero,ref scheme,ref video,ref setting,out value)!=0) throw new InvalidOperationException();
        return value;
    }
    static void SetTimeout(Guid scheme,uint value) {
        Guid video=Video, setting=LockTimeout;
        if(PowerWriteACValueIndex(IntPtr.Zero,ref scheme,ref video,ref setting,value)!=0) throw new InvalidOperationException();
        if(ActiveScheme()==scheme && PowerSetActiveScheme(IntPtr.Zero,ref scheme)!=0) throw new InvalidOperationException();
    }
    static string ConsoleState() {
        uint session=WTSGetActiveConsoleSessionId(); IntPtr buffer; int size;
        if(session!=(uint)Process.GetCurrentProcess().SessionId || !WTSQuerySessionInformation(IntPtr.Zero,session,25,out buffer,out size)) return "unavailable";
        try {
            if(size<Marshal.SizeOf(typeof(WTSINFOEX))) return "unavailable";
            var info=(WTSINFOEX)Marshal.PtrToStructure(buffer,typeof(WTSINFOEX));
            if(info.Level!=1 || info.Data.SessionId!=session || info.Data.SessionState!=0) return "unavailable";
            return info.Data.SessionFlags==0?"locked":info.Data.SessionFlags==1?"unlocked":"unavailable";
        } finally { WTSFreeMemory(buffer); }
    }
    static int SelfTest() {
        string ticket; long issued; int pid;
        string valid=new string('a',32)+"|100000|42";
        if(!ParseRequest(valid,100000,out ticket,out issued,out pid)) return 1;
        if(ParseRequest(valid,120000,out ticket,out issued,out pid) || ParseRequest(valid,90000,out ticket,out issued,out pid)) return 2;
        if(ParseRequest("path|100000|42",100000,out ticket,out issued,out pid)) return 3;
        if(ParseOverride("[SERVICE]\nAntigravity.exe SYSTEM\n[PROCESS]\nother.exe DISPLAY\n")!="") return 4;
        if(ParseOverride("[PROCESS]\nAntigravity.exe SYSTEM DISPLAY\n")!="DISPLAY SYSTEM") return 5;
        if(AddDisplay("SYSTEM")!="DISPLAY SYSTEM" || AddDisplay("")!="DISPLAY") return 6;
        try { Normalize("DISPLAY & calc.exe"); return 7; } catch(InvalidDataException) {}
        Console.WriteLine("PASS: request freshness, fixed target, override preservation, argument rejection. No system settings changed."); return 0;
    }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct WTSINFOEX_LEVEL1 {
        public uint SessionId; public int SessionState,SessionFlags;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=33)] public string WinStationName;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=21)] public string UserName;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=18)] public string DomainName;
        public long LogonTime,ConnectTime,DisconnectTime,LastInputTime,CurrentTime;
        public uint IncomingBytes,OutgoingBytes,IncomingFrames,OutgoingFrames,IncomingCompressedBytes,OutgoingCompressedBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct WTSINFOEX { public uint Level; public WTSINFOEX_LEVEL1 Data; }
    [DllImport("kernel32.dll")] static extern uint WTSGetActiveConsoleSessionId();
    [DllImport("wtsapi32.dll",CharSet=CharSet.Unicode)] static extern bool WTSQuerySessionInformation(IntPtr server,uint session,int info,out IntPtr buffer,out int size);
    [DllImport("wtsapi32.dll")] static extern void WTSFreeMemory(IntPtr buffer);
    [DllImport("powrprof.dll")] static extern uint PowerGetActiveScheme(IntPtr root,out IntPtr scheme);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
    [DllImport("powrprof.dll")] static extern uint PowerReadACValueIndex(IntPtr root,ref Guid scheme,ref Guid subgroup,ref Guid setting,out uint value);
    [DllImport("powrprof.dll")] static extern uint PowerWriteACValueIndex(IntPtr root,ref Guid scheme,ref Guid subgroup,ref Guid setting,uint value);
    [DllImport("powrprof.dll")] static extern uint PowerSetActiveScheme(IntPtr root,ref Guid scheme);
}
