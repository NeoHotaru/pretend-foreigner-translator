# Focused editable controls only. Requests and replies use JSON over standard IO.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    if ($request.action -eq 'read-selection' -or $request.action -eq 'read-reference' -or $null -ne $request.selection) {
        Add-Type -AssemblyName System.Web.Extensions
        $frameworkFolder = [System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()
        $references = @((Join-Path $frameworkFolder 'WPF/UIAutomationClient.dll'),
            (Join-Path $frameworkFolder 'WPF/UIAutomationTypes.dll'),
            (Join-Path $frameworkFolder 'WPF/WindowsBase.dll'),
            (Join-Path $frameworkFolder 'System.Web.Extensions.dll'))
        Add-Type -Path (Join-Path $PSScriptRoot 'selection-bridge.cs') -ReferencedAssemblies $references
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential)] public struct InputKeyboard {
    public ushort vk, scan; public uint flags, time; public UIntPtr extra;
}
[StructLayout(LayoutKind.Sequential)] public struct InputMouse {
    public int x, y; public uint data, flags, time; public UIntPtr extra;
}
[StructLayout(LayoutKind.Explicit)] public struct InputData {
    [FieldOffset(0)] public InputKeyboard keyboard;
    [FieldOffset(0)] public InputMouse mouse;
}
[StructLayout(LayoutKind.Sequential)] public struct NativeInput { public uint type; public InputData data; }
public static class InputForeground {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint count, NativeInput[] input, int size);
    static NativeInput Key(ushort vk, ushort scan, uint flags) {
        return new NativeInput {type=1, data=new InputData {keyboard=new InputKeyboard {vk=vk,scan=scan,flags=flags}}};
    }
    public static void Insert(string text, bool selectAll) {
        foreach(int key in new int[]{16,17,18,91,92})
            if((GetAsyncKeyState(key)&0x8000)!=0) throw new Exception("Shortcut keys are still held");
        foreach(char ch in text) if(ch<32 || ch==127) throw new Exception("Multiline translation requires manual paste");
        int prefix=selectAll?4:0;
        var inputs=new NativeInput[prefix+(text.Length==0?2:text.Length*2)];
        if(selectAll){inputs[0]=Key(17,0,0); inputs[1]=Key(65,0,0); inputs[2]=Key(65,0,2); inputs[3]=Key(17,0,2);}
        for(int i=0;i<text.Length;i++){inputs[prefix+i*2]=Key(0,text[i],4); inputs[prefix+i*2+1]=Key(0,text[i],6);}
        if(text.Length==0){inputs[prefix]=Key(8,0,0);inputs[prefix+1]=Key(8,0,2);}
        if(SendInput((uint)inputs.Length,inputs,Marshal.SizeOf(typeof(NativeInput)))!=inputs.Length)
            throw new Exception("Input delivery incomplete; check the original field");
    }
}
'@
    if ([InputForeground]::GetForegroundWindow().ToInt64() -ne [long]$request.window) {
        throw 'Input window changed'
    }
    if ($request.action -eq 'read-reference') {
        $reference = [PftSelection]::Read(0)
        if ($null -eq $reference -or $reference['purpose'] -ne 'reference' -or
            $reference['identity'] -ne $request.selection.identity -or
            $reference['selected'] -cne $request.selection.selected) {
            throw 'Reference selection changed'
        }
        [Console]::WriteLine((@{ok=$true; selected=$reference['selected']} | ConvertTo-Json -Compress))
        exit 0
    }
    $element = [System.Windows.Automation.AutomationElement]::FocusedElement
    if ($null -eq $element -or $element.Current.IsPassword -or -not $element.Current.IsEnabled) {
        throw 'No ordinary editable control is focused'
    }
    $value = $null
    if (-not $element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value) -or
        $value.Current.IsReadOnly) {
        throw 'This control does not support accessible text replacement'
    }
    $identity = @($element.GetRuntimeId()) -join ','
    $original = $value.Current.Value
    $selectedSnapshot = $null
    if ($request.action -eq 'read-selection' -or $null -ne $request.selection) {
        $selectedSnapshot = [PftSelection]::Read(0)
        if ($null -eq $selectedSnapshot -or $null -eq $request.selection -or
            $selectedSnapshot['identity'] -ne $request.selection.identity -or
            $selectedSnapshot['value'] -cne $request.selection.value -or
            $selectedSnapshot['prefix'] -cne $request.selection.prefix -or
            $selectedSnapshot['selected'] -cne $request.selection.selected) {
            throw 'Selection or input draft changed'
        }
    }
    if ($request.action -eq 'replace') {
        if ($identity -ne $request.identity -or $original -cne $request.original) {
            throw 'Input field or draft changed'
        }
        # Chromium SetValue on contenteditable can bypass the framework's input
        # event. Select this field's text and type Unicode instead, so ProseMirror
        # and controlled inputs update their own draft state too.
        if ([string]$request.translation -match '[\x00-\x1f\x7f]') {
            throw 'Multiline translation requires manual paste'
        }
        $textPattern = $null
        $selectAll = $false
        $expected = [string]$request.translation
        if ($element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$textPattern)) {
            if ($null -ne $selectedSnapshot) {
                $textPattern.GetSelection()[0].Select()
                $expected = $selectedSnapshot['prefix'] + [string]$request.translation + $selectedSnapshot['suffix']
            } else {
                $textPattern.DocumentRange.Select()
            }
        } elseif ($element.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit) {
            $selectAll = $true
        } else { throw 'This control does not support accessible text replacement' }
        if ([InputForeground]::GetForegroundWindow().ToInt64() -ne [long]$request.window -or
            ((@([System.Windows.Automation.AutomationElement]::FocusedElement.GetRuntimeId()) -join ',') -ne $identity)) {
            throw 'Input field changed'
        }
        [InputForeground]::Insert([string]$request.translation, $selectAll)
        $deadline = [DateTime]::UtcNow.AddSeconds(2)
        do {
            Start-Sleep -Milliseconds 30
            $actual = $value.Current.Value
        } while ($actual -cne $expected -and [DateTime]::UtcNow -lt $deadline)
        if ($actual -cne $expected) {
            throw 'The input control did not accept the complete translation; check the original field'
        }
        $response = @{ok=$true; identity=$identity; value=$actual}
    } elseif ($request.action -eq 'read-selection') {
        $response = @{ok=$true; identity=$identity; value=$original; selected=$selectedSnapshot['selected']}
    } elseif ($request.action -eq 'read') {
        $response = @{ok=$true; identity=$identity; value=$original}
    } else { throw 'Unknown action' }
    [Console]::WriteLine(($response | ConvertTo-Json -Compress))
} catch {
    [Console]::WriteLine((@{ok=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress))
    exit 1
}
