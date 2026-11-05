// Explicit no-PIN diagnostic. At most one successful fixed Space on genuine LockApp.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
public static class CurtainInputProbe {
 [DllImport("user32.dll",SetLastError=true)] static extern IntPtr OpenInputDesktop(uint f,bool inherit,uint access);
 [DllImport("user32.dll",SetLastError=true)] static extern bool SetThreadDesktop(IntPtr d);
 [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr d);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr w,out uint p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode,EntryPoint="GetUserObjectInformationW")] static extern bool Info(IntPtr d,int n,StringBuilder b,uint size,out uint needed);
 [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint n,INPUT[] data,int size);
 [StructLayout(LayoutKind.Explicit,Size=40)] struct INPUT {
  [FieldOffset(0)] public uint type; [FieldOffset(8)] public ushort vk;
  [FieldOffset(12)] public uint flags;
 }
 static bool IsLockApp(IntPtr window) {
  uint pid;GetWindowThreadProcessId(window,out pid);
  try {using(var p=Process.GetProcessById((int)pid)) {
   return p.SessionId==Process.GetCurrentProcess().SessionId && p.ProcessName=="LockApp" &&
    p.MainModule.FileName.StartsWith(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),"SystemApps")+"\\",StringComparison.OrdinalIgnoreCase);
  }} catch {return false;}
 }
 static int TryMask(uint access) {
  int sent=-1;IntPtr desk=IntPtr.Zero;
  Thread t=new Thread(()=> {
   desk=OpenInputDesktop(0,false,access);
   if(desk==IntPtr.Zero) {Console.WriteLine("open_error="+Marshal.GetLastWin32Error());return;}
   var name=new StringBuilder(64);uint need;
   if(!Info(desk,2,name,128,out need) || name.ToString()!="Default") {Console.WriteLine("not_clock_desktop");return;}
   if(!SetThreadDesktop(desk)) {Console.WriteLine("attach_error="+Marshal.GetLastWin32Error());return;}
   IntPtr window=GetForegroundWindow();if(!IsLockApp(window)) {Console.WriteLine("not_verified_lockapp");return;}
   if(GetForegroundWindow()!=window) {Console.WriteLine("foreground_changed");return;}
   var keys=new[]{new INPUT{type=1,vk=0x20},new INPUT{type=1,vk=0x20,flags=2}};
   sent=(int)SendInput(2,keys,40);int error=Marshal.GetLastWin32Error();Array.Clear(keys,0,keys.Length);
   Console.WriteLine("mask="+access.ToString("X")+";sent="+sent+";win32="+error+";pin_sent=false");
  });
  t.IsBackground=true;t.SetApartmentState(ApartmentState.MTA);t.Start();
  bool done=t.Join(3000);if(done&&desk!=IntPtr.Zero)CloseDesktop(desk);
  return done?sent:-1;
 }
 public static int Main() {
  if(Environment.GetCommandLineArgs().Length!=2 || Environment.GetCommandLineArgs()[1]!="--fixed-space-on-lockapp") return 2;
  // A zero-event failure may be compared once with the playback right added.
  // Any success, partial success or unverifiable target stops the diagnostic.
  if(TryMask(0x81)==0) TryMask(0xA1);
  return 0;
 }
}
