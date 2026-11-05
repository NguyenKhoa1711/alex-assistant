// Component tests only. No service installation, key injection, lock or real PIN.
using System;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading.Tasks;

internal class UnlockLab {
    static int passed,failed;
    static readonly Type Target=typeof(AlexUnlock);
    static object Invoke(string name,params object[] args) {
        try { return Target.GetMethod(name,BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,args); }
        catch(TargetInvocationException e) { throw e.InnerException; }
    }
    static void Check(string name,Func<bool> test) {
        try { if(!test()) throw new Exception("assertion"); passed++; Console.WriteLine("PASS "+name); }
        catch(Exception e) { failed++; Console.WriteLine("FAIL "+name+": "+e.GetType().Name); }
    }
    static bool BadFrame(byte[] frame) {
        try { Invoke("ReadPin",new MemoryStream(frame)); return false; }
        catch(InvalidDataException) { return true; }
        catch(EndOfStreamException) { return true; }
    }
    public static int Main() {
        // Rate-limit file stays beside this disposable test binary, never the installed path.
        string path=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"attempts.txt");
        if(File.Exists(path)) { Console.WriteLine("Refusing a non-empty test directory"); return 2; }
        Check("minimum-four-digits",()=> (bool)Invoke("ValidPin",new byte[]{49,50,51,52}));
        Check("maximum-twenty-digits",()=> (bool)Invoke("ValidPin",Encoding.ASCII.GetBytes(new string('1',20))));
        Check("empty-pin-rejected",()=> !(bool)Invoke("ValidPin",new byte[0]));
        Check("three-digits-rejected",()=> !(bool)Invoke("ValidPin",new byte[]{49,50,51}));
        Check("long-pin-rejected",()=> !(bool)Invoke("ValidPin",new byte[21]));
        Check("non-digits-rejected",()=> !(bool)Invoke("ValidPin",new byte[]{49,50,65,52}));
        Check("truncated-frame-rejected",()=>BadFrame(new byte[]{4,49,50}));
        Check("zero-frame-rejected",()=>BadFrame(new byte[]{0}));
        Check("oversize-frame-rejected",()=>BadFrame(new byte[]{255}));
        Check("newline-in-pin-rejected",()=>BadFrame(new byte[]{4,49,50,10,52}));
        Check("valid-frame-parsed",()=> { var b=(byte[])Invoke("ReadPin",new MemoryStream(new byte[]{4,49,50,51,52})); bool ok=b.Length==4; Array.Clear(b,0,b.Length); return ok; });
        Check("vietnamese-pin-label",()=> (bool)Invoke("IsPinName","Mã PIN"));
        Check("password-not-pin",()=> !(bool)Invoke("IsPinName","Password"));
        Check("substring-not-pin",()=> !(bool)Invoke("IsPinName","spinning"));
        Check("missing-label-not-pin",()=> !(bool)Invoke("IsPinName",new object[]{null}));
        Check("first-attempt",()=> (bool)Invoke("ReserveAttempt"));
        Check("second-attempt",()=> (bool)Invoke("ReserveAttempt"));
        Check("third-attempt",()=> (bool)Invoke("ReserveAttempt"));
        Check("fourth-blocked",()=> !(bool)Invoke("ReserveAttempt"));
        Check("limit-persists-in-file",()=>File.ReadAllLines(path).Length==3);
        Check("old-attempt-expires",()=> {File.WriteAllText(path,DateTime.UtcNow.AddSeconds(-61).Ticks.ToString()); return (bool)Invoke("ReserveAttempt");});
        Check("clock-rollback-fails-closed",()=> {string t=DateTime.UtcNow.AddHours(1).Ticks.ToString();File.WriteAllLines(path,new[]{t,t,t});return !(bool)Invoke("ReserveAttempt");});
        Check("corrupt-limit-fails-closed",()=> {File.WriteAllText(path,"invalid");return !(bool)Invoke("ReserveAttempt");});
        Check("readonly-console-state",()=> {string s=(string)Invoke("ConsoleState"); return s=="locked"||s=="unlocked"||s=="unavailable";});
        Check("real-named-pipe-authorized-local-client",()=> PipeTest(false));
        Check("real-named-pipe-unknown-command-rejected",()=> PipeTest(true));
        Check("windows-requires-read-before-identity",()=> {try {IdentityTest(false);return false;} catch(AggregateException) {return true;}});
        Check("identity-after-first-read",()=> IdentityTest(true));
        Check("service-peer-identity-reads-first",()=> IdentityFixedTest());
        Check("delivery-rejects-invalid-pin",()=> DeliveryTest("invalid"));
        Check("delivery-rejects-unverified-target",()=> DeliveryTest("unverified"));
        Check("delivery-preflight-exception-sends-nothing",()=> DeliveryTest("preflight-error"));
        Check("delivery-writes-and-submits-once",()=> DeliveryTest("success"));
        Check("auto-unlock-does-not-submit-again",()=> DeliveryTest("auto"));
        Check("changed-target-after-write-does-not-submit",()=> DeliveryTest("target-changed"));
        Check("write-error-does-not-retry",()=> DeliveryTest("write-error"));
        Check("submit-error-does-not-retry",()=> DeliveryTest("submit-error"));
        Check("state-error-after-write-does-not-submit",()=> DeliveryTest("state-error"));
        Check("diagnostics-allow-fixed-code",()=> (string)Invoke("SafeHelperResult","diag_pin_missing",true)=="diag_pin_missing");
        Check("diagnostics-reject-arbitrary-data",()=> (string)Invoke("SafeHelperResult","private value 999999",true)=="unknown_result");
        Check("unlock-result-rejects-arbitrary-data",()=> (string)Invoke("SafeHelperResult","private value 999999",false)=="unknown_result");
        Check("unlock-result-rejects-diagnostic-code",()=> (string)Invoke("SafeHelperResult","diag_ready",false)=="unknown_result");
        Check("submit-button-may-become-available-after-value",()=> DeliveryTest("delayed-submit"));
        Check("async-auto-unlock-observed-without-resubmission",()=> {
            int reads=0,waits=0;
            string r=(string)Invoke("ObserveUnlockResult","unknown_result",(Func<string>)(()=>++reads<3?"locked":"unlocked"),(Action)(()=>waits++));
            return r=="unlocked" && reads==3 && waits==2;
        });
        Check("unlock-observation-times-out-bounded",()=> {
            int reads=0,waits=0;
            string r=(string)Invoke("ObserveUnlockResult","submitted",(Func<string>)(()=>{reads++;return "locked";}),(Action)(()=>waits++));
            return r=="unknown_result" && reads==40 && waits==40;
        });
        Check("preflight-failure-does-not-observe-or-wait",()=> {
            string r=(string)Invoke("ObserveUnlockResult","pin_field_unavailable",(Func<string>)(()=>{throw new Exception();}),(Action)(()=>{throw new Exception();}));
            return r=="pin_field_unavailable";
        });
        Check("clock-curtain-may-be-dismissed",()=> (bool)Invoke("ShouldDismissCurtain",true,true,false));
        Check("unlocked-desktop-never-receives-curtain-key",()=> !(bool)Invoke("ShouldDismissCurtain",false,true,false));
        Check("other-window-never-receives-curtain-key",()=> !(bool)Invoke("ShouldDismissCurtain",true,false,false));
        Check("visible-pin-or-password-never-receives-space",()=> !(bool)Invoke("ShouldDismissCurtain",true,true,true));
        Check("default-desktop-allows-only-lock-app",()=>
            (bool)Invoke("CurtainWindowAllowed","Default",true,false) &&
            !(bool)Invoke("CurtainWindowAllowed","Default",false,true) &&
            !(bool)Invoke("CurtainWindowAllowed","Default",false,false));
        Check("winlogon-allows-verified-logon-window",()=> (bool)Invoke("CurtainWindowAllowed","Winlogon",false,true));
        Check("other-desktops-rejected-even-for-trusted-process",()=> !(bool)Invoke("CurtainWindowAllowed","Other",true,true));
        Check("credential-delivery-only-after-curtain-ready",()=> {
            int stage=0;
            string result=(string)Invoke("PrepareThenDeliver",(Func<string>)(()=>{if(stage++!=0) throw new Exception();return "pin_desktop_ready";}),
                (Func<string>)(()=>{if(stage++!=1) throw new Exception();return "unlocked";}));
            return stage==2 && result=="unlocked";
        });
        Check("failed-curtain-never-releases-pin",()=> {
            foreach(string code in new[]{"not_locked","pin_field_unavailable","helper_unavailable","unknown_result"}) {
                string result=(string)Invoke("PrepareThenDeliver",(Func<string>)(()=>code),(Func<string>)(()=>{throw new Exception("must not deliver");}));
                if(result!=code) return false;
            }
            return true;
        });
        Check("preparation-result-cannot-smuggle-data",()=> (string)Invoke("SafePreparationResult","123456") == "unknown_result");
        Check("preparation-ready-is-not-unlock-success",()=> (string)Invoke("SafeHelperResult","pin_desktop_ready",false) == "unknown_result");
        Check("prepare-only-rejects-unlocked-without-action",()=>
            (string)Invoke("PrepareOnly",(Func<string>)(()=>"unlocked"),(Func<bool>)(()=>{throw new Exception();}),
                (Func<string>)(()=>{throw new Exception();})) == "not_locked");
        Check("prepare-only-obeys-rate-limit-without-action",()=>
            (string)Invoke("PrepareOnly",(Func<string>)(()=>"locked"),(Func<bool>)(()=>false),
                (Func<string>)(()=>{throw new Exception();})) == "rate_limited");
        Check("prepare-only-invokes-one-fixed-operation",()=> {
            int count=0;
            string result=(string)Invoke("PrepareOnly",(Func<string>)(()=>"locked"),(Func<bool>)(()=>true),
                (Func<string>)(()=>{count++;return "pin_desktop_ready";}));
            return count==1 && result=="pin_desktop_ready";
        });
        Console.WriteLine("RESULT passed="+passed+" failed="+failed+"; no keys sent; no service installed");
        return failed==0?0:1;
    }
    static bool DeliveryTest(string scenario) {
        int verified=0,writes=0,submits=0;
        byte[] pin=scenario=="invalid"?new byte[]{49}:new byte[]{49,50,51,52};
        Func<bool> check=()=> {
            verified++;
            if(scenario=="preflight-error") throw new InvalidOperationException();
            return scenario!="unverified" && !(scenario=="target-changed" && verified>1);
        };
        Action<byte[]> write=data=> {
            writes++;
            if(!object.ReferenceEquals(data,pin)) throw new InvalidOperationException();
            if(scenario=="write-error") throw new InvalidOperationException();
        };
        Func<string> state=()=> {
            if(scenario=="state-error") throw new InvalidOperationException();
            return scenario=="auto"?"unlocked":"locked";
        };
        Action submit=()=> {
            if(scenario=="delayed-submit" && writes!=1) throw new InvalidOperationException();
            submits++; if(scenario=="submit-error") throw new InvalidOperationException();
        };
        string result=(string)Invoke("DeliverOnce",pin,check,write,state,submit);
        Array.Clear(pin,0,pin.Length);
        if(scenario=="invalid") return result=="invalid_request" && writes==0 && submits==0;
        if(scenario=="unverified" || scenario=="preflight-error") return result=="pin_field_unavailable" && writes==0 && submits==0;
        if(scenario=="success" || scenario=="delayed-submit") return result=="submitted" && writes==1 && submits==1;
        if(scenario=="auto") return result=="unlocked" && writes==1 && submits==0;
        if(scenario=="submit-error") return result=="unknown_result" && writes==1 && submits==1;
        return result=="unknown_result" && writes==1 && submits==0;
    }
    static bool PipeTest(bool unknown) {
        string name="Alex.Unlock.Test."+Guid.NewGuid().ToString("N");
        var sid=WindowsIdentity.GetCurrent().User;
        using(var server=(NamedPipeServerStream)Invoke("NewPipe",name,sid)) {
            var task=Task.Run(()=> {
                server.WaitForConnection();
                // Status and unknown opcode only. Never send operation 1 (PIN).
                Invoke("Handle",server,(uint)0,server.ReadByte());
            });
            using(var client=new NamedPipeClientStream(".",name,PipeDirection.InOut)) {
                client.Connect(2000); client.WriteByte(unknown?(byte)255:(byte)0); client.Flush();
                var read=Task.Run(()=> {using(var r=new StreamReader(client,Encoding.ASCII)) return r.ReadLine();});
                if(!read.Wait(3000)) {client.Dispose();return false;}
                if(!task.Wait(3000)) return false;
                return unknown?read.Result=="invalid_request":new[]{"unlocked","locked","unavailable"}.Contains(read.Result);
            }
        }
    }
    static bool IdentityTest(bool readFirst) {
        string name="Alex.Unlock.Test."+Guid.NewGuid().ToString("N");
        var sid=WindowsIdentity.GetCurrent().User;
        using(var server=(NamedPipeServerStream)Invoke("NewPipe",name,sid)) {
            var task=Task.Run(()=> {
                server.WaitForConnection();
                if(readFirst) server.ReadByte();
                string result="";
                server.RunAsClient(()=>{result=WindowsIdentity.GetCurrent().User.Value;});
                return result==sid.Value;
            });
            using(var client=new NamedPipeClientStream(".",name,PipeDirection.InOut)) {
                client.Connect(2000);
                System.Threading.Thread.Sleep(100);
                client.WriteByte(0); client.Flush();
                return task.Wait(2000) && task.Result;
            }
        }
    }
    static bool IdentityFixedTest() {
        string name="Alex.Unlock.Test."+Guid.NewGuid().ToString("N");
        var sid=WindowsIdentity.GetCurrent().User;
        using(var server=(NamedPipeServerStream)Invoke("NewPipe",name,sid)) {
            var task=Task.Run(()=> {
                server.WaitForConnection();
                object[] arguments={server,0};
                string actual=(string)Invoke("ReadPeerIdentity",arguments);
                return actual==sid.Value && (int)arguments[1]==0;
            });
            using(var client=new NamedPipeClientStream(".",name,PipeDirection.InOut)) {
                client.Connect(2000);System.Threading.Thread.Sleep(100);client.WriteByte(0);client.Flush();
                return task.Wait(2000) && task.Result;
            }
        }
    }
}
