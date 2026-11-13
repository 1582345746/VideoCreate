"""Check form drafts before user-requested close, without saving or executing."""
import hashlib
import json
import tkinter as tk
from tkinter import ttk, messagebox


_UNSET = object()


def controls(parent):
    """Digest raw static controls, including invalid input, excluding child windows.

    Only the digest is retained: a credential draft never enters diagnostics.
    Tree selections and disabled report text are presentation, not edits.
    """
    rows = []
    def visit(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Toplevel):continue
            if isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Entry, tk.Spinbox)):
                rows.append((str(child), child.get()))
            elif isinstance(child, tk.Text) and str(child.cget('state')) != 'disabled':
                rows.append((str(child), child.get('1.0', 'end-1c')))
            elif isinstance(child, (ttk.Checkbutton, ttk.Radiobutton)):
                variable = child.cget('variable')
                rows.append((str(child), str(child.getvar(variable))))
            elif isinstance(child, ttk.Treeview):
                def items(node=''):
                    return [(child.item(key, 'text'), child.item(key, 'values'), items(key))
                            for key in child.get_children(node)]
                rows.append((str(child), items()))
            visit(child)
    visit(parent)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest()


def guards(parent):
    """Deepest windows first; checking never destroys or commits a draft."""
    result = []
    for child in parent.winfo_children():result.extend(guards(child))
    guard = getattr(parent, 'draft_guard', None)
    if guard is not None:result.append(guard)
    return result


def confirm_close(parent, *, scope=None):
    pending = [guard for guard in guards(parent) if scope is None or guard.scope == scope]
    # Do not ask to discard one form if another local transaction blocks exit.
    for guard in pending:
        if guard.busy():
            messagebox.showinfo('操作正在完成', '请等待当前本地操作完成，再关闭窗口。', parent=guard.window)
            return False
    return all(guard.confirm() for guard in pending)


class DraftGuard:
    def __init__(self, window, *, read=None, value=_UNSET, label='表单', busy=lambda:False, scope='form'):
        self.window, self.read, self.label, self.busy = window, read or (lambda:controls(window)), label, busy
        self.scope = scope
        self.initial = self.read() if value is _UNSET else value
        window.draft_guard = self
        window.protocol('WM_DELETE_WINDOW', self.close)

    def reset(self):
        self.initial = self.read()

    def dirty(self):
        try:return self.read() != self.initial
        except (ValueError, OSError, tk.TclError):return True

    def confirm(self):
        return not self.dirty() or messagebox.askyesno('尚未应用或保存的修改',
            '关闭并放弃“' + self.label + '”中的修改？\n继续编辑请选择“否”。', parent=self.window)

    def close(self):
        if confirm_close(self.window):self.window.destroy()
