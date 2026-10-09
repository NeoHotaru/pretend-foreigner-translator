using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Automation;
using System.Windows.Automation.Text;

public static class PftSelection {
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window,StringBuilder text,int length);

    public static Dictionary<string,object> Read(int ownerProcess) {
        return Read(ownerProcess,null);
    }
    static Dictionary<string,object> Read(int ownerProcess,string windowPrefix) {
        IntPtr window=GetForegroundWindow(); uint process;
        GetWindowThreadProcessId(window,out process);
        if(window==IntPtr.Zero || process==ownerProcess) return null;
        if(!String.IsNullOrEmpty(windowPrefix)) {
            StringBuilder title=new StringBuilder(4096); GetWindowText(window,title,title.Capacity);
            if(!title.ToString().StartsWith(windowPrefix,StringComparison.Ordinal)) return null;
        }
        AutomationElement element=AutomationElement.FocusedElement;
        if(element==null || element.Current.IsPassword || !element.Current.IsEnabled) return null;
        object valueObject,textObject;
        ValuePattern value=element.TryGetCurrentPattern(ValuePattern.Pattern,out valueObject)?(ValuePattern)valueObject:null;
        if(element.TryGetCurrentPattern(TextPattern.Pattern,out textObject)) {
            var selected=Snapshot(element,(TextPattern)textObject,value,window,process);
            if(selected!=null) return selected;
        }
        // A browser may leave keyboard focus on the editor when the user selects
        // a received message. Its ancestor document owns that readonly range.
        AutomationElement parent=element;
        for(int depth=0;depth<18 && parent!=null;depth++) {
            parent=TreeWalker.ControlViewWalker.GetParent(parent);
            if(parent!=null && parent.Current.ControlType==ControlType.Document &&
               parent.TryGetCurrentPattern(TextPattern.Pattern,out textObject)) {
                var selected=Snapshot(parent,(TextPattern)textObject,null,window,process);
                if(selected!=null) return selected;
            }
        }
        AutomationElement root=AutomationElement.FromHandle(window);
        AutomationElement document=root.FindFirst(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.ControlTypeProperty,ControlType.Document));
        if(document!=null && !document.Current.IsOffscreen &&
           document.TryGetCurrentPattern(TextPattern.Pattern,out textObject))
            return Snapshot(document,(TextPattern)textObject,null,window,process);
        return null;
    }

    static Dictionary<string,object> Snapshot(AutomationElement element,TextPattern text,
            ValuePattern value,IntPtr window,uint process) {
        TextPatternRange[] selected=text.GetSelection();
        if(selected.Length!=1) return null;
        string selection=selected[0].GetText(12001);
        if(String.IsNullOrWhiteSpace(selection) || selection.Length>12000) return null;
        System.Windows.Rect[] rectangles=selected[0].GetBoundingRectangles();
        if(rectangles.Length==0) return null;
        System.Windows.Rect last=rectangles[rectangles.Length-1];
        if(last.IsEmpty || last.Width<=0 || last.Height<=0 || GetForegroundWindow()!=window) return null;
        bool editable=value!=null && !value.Current.IsReadOnly;
        var snapshot=new Dictionary<string,object> {
            {"window",window.ToInt64()}, {"process_id",process},
            {"identity",String.Join(",",element.GetRuntimeId())},
            {"selected",selection}, {"purpose",editable?"translate":"reference"},
            {"bounds",new double[]{last.X,last.Y,last.Width,last.Height}}
        };
        if(!editable) {
            object readonlyAttribute=selected[0].GetAttributeValue(TextPattern.IsReadOnlyAttribute);
            if(!(value!=null && value.Current.IsReadOnly) &&
               !(readonlyAttribute is bool && (bool)readonlyAttribute)) return null;
            var enclosing=selected[0].GetEnclosingElement();
            snapshot["identity"]+="|"+String.Join(",",enclosing.GetRuntimeId());
            return snapshot;
        }
        string original=value.Current.Value;
        if(original.Length>50000) return null;
        TextPatternRange before=text.DocumentRange.Clone();
        before.MoveEndpointByRange(TextPatternRangeEndpoint.End,selected[0],TextPatternRangeEndpoint.Start);
        string prefix=before.GetText(-1);
        // Require exact offsets. Never guess where repeated phrases belong.
        if(prefix.Length+selection.Length>original.Length ||
           !original.StartsWith(prefix,StringComparison.Ordinal) ||
           original.Substring(prefix.Length,selection.Length)!=selection) return null;
        if(GetForegroundWindow()!=window) return null;
        snapshot["value"]=original; snapshot["prefix"]=prefix;
        snapshot["suffix"]=original.Substring(prefix.Length+selection.Length);
        return snapshot;
    }

    public static void Watch(int ownerProcess,string windowPrefix) {
        JavaScriptSerializer serializer=new JavaScriptSerializer();
        string previous=null;
        while(true) {
            Dictionary<string,object> snapshot=null;
            try { snapshot=Read(ownerProcess,windowPrefix); } catch { }
            string next=snapshot==null?null:serializer.Serialize(snapshot);
            if(next!=previous) {
                Console.WriteLine(next==null?"{\"type\":\"clear\"}":"{\"type\":\"selection\",\"snapshot\":"+next+"}");
                Console.Out.Flush(); previous=next;
            }
            Thread.Sleep(250);
        }
    }
}
