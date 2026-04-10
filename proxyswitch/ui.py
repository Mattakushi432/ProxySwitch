import platform
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk  # type: ignore
import tkinter as tk
from tkinter import messagebox

from .config import (
    APP_NAME,
    APP_VERSION,
    C,
    LOCAL_PROXY_PORT,
    PROXY_TYPES,
    S_DOT,
    S_FAIL,
    S_IDLE,
    S_OK,
    S_TESTING,
    TYPE_BADGE,
    logger,
)
from .connections import RoutingProxy, clear_system_proxy, set_system_proxy_to_local, test_local_proxy, test_proxy
from .storage import ProfileStore


class ProfileDialog(ctk.CTkToplevel):
    def __init__(self, master: Any, profile: Optional[Dict[str, Any]] = None, on_save: Optional[Callable] = None) -> None:
        super().__init__(master)
        self.on_save: Optional[Callable] = on_save
        self.profile: Dict[str, Any] = profile or {}
        self._rules: List[Dict[str, Any]] = list(self.profile.get("rules", []))

        self.title("Редактировать профиль" if profile else "Новый профиль")
        self.geometry("560x700")
        self.resizable(False, True)
        self.configure(fg_color=C["panel"])
        try:
            self.grab_set()
        except tk.TclError:
            logger.warning("Could not set grab on dialog")
        try:
            self.lift()
            self.focus()
        except tk.TclError:
            logger.warning("Could not lift/focus dialog")

        self.tabs = ctk.CTkTabview(
            self,
            fg_color=C["card"],
            segmented_button_fg_color=C["panel"],
            segmented_button_selected_color=C["accent"],
            segmented_button_selected_hover_color=C["accent2"],
            segmented_button_unselected_color=C["panel"],
            segmented_button_unselected_hover_color=C["card_hover"],
            text_color=C["text"],
            border_width=0,
        )
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        self.tabs.add("Основное")
        self.tabs.add("Авторизация")
        self.tabs.add("Правила")

        self._build_tab_main()
        self._build_tab_auth()
        self._build_tab_rules()

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            row,
            text="Отмена",
            fg_color=C["card"],
            hover_color=C["card_hover"],
            text_color=C["text_muted"],
            font=("JetBrains Mono", 13),
            height=38,
            command=self.destroy,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(
            row,
            text="Сохранить",
            fg_color=C["accent"],
            hover_color=C["accent2"],
            text_color="#000",
            font=("JetBrains Mono", 13, "bold"),
            height=38,
            command=self._save,
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    def _lbl(self, parent: Any, text: str) -> None:
        ctk.CTkLabel(parent, text=text, font=("JetBrains Mono", 11), text_color=C["text_muted"]).pack(
            anchor="w", padx=4, pady=(10, 2)
        )

    def _entry(self, parent: Any, default: str = "", show: str = "") -> ctk.CTkEntry:
        e = ctk.CTkEntry(
            parent,
            height=36,
            fg_color=C["bg"],
            border_color=C["border"],
            text_color=C["text"],
            font=("JetBrains Mono", 13),
            show=show,
        )
        e.pack(fill="x", padx=4)
        if default:
            e.insert(0, str(default))
        return e

    def _build_tab_main(self) -> None:
        t = self.tabs.tab("Основное")
        p = self.profile

        self._lbl(t, "Название профиля")
        self.e_name = self._entry(t, p.get("name", ""))

        self._lbl(t, "Тип прокси")
        self.v_type = ctk.StringVar(value=p.get("type", "HTTP"))
        ctk.CTkOptionMenu(
            t,
            values=PROXY_TYPES,
            variable=self.v_type,
            fg_color=C["bg"],
            button_color=C["accent_dim"],
            button_hover_color=C["accent"],
            dropdown_fg_color=C["card"],
            text_color=C["text"],
            font=("JetBrains Mono", 13),
            height=36,
        ).pack(fill="x", padx=4, pady=(0, 0))

        row = ctk.CTkFrame(t, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(10, 0))

        lc = ctk.CTkFrame(row, fg_color="transparent")
        lc.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkLabel(lc, text="Host", font=("JetBrains Mono", 11), text_color=C["text_muted"]).pack(anchor="w", pady=(0, 2))
        self.e_host = ctk.CTkEntry(
            lc, height=36, fg_color=C["bg"], border_color=C["border"], text_color=C["text"], font=("JetBrains Mono", 13)
        )
        self.e_host.pack(fill="x")
        if p.get("host"):
            self.e_host.insert(0, p["host"])

        rc = ctk.CTkFrame(row, fg_color="transparent", width=100)
        rc.pack(side="left")
        rc.pack_propagate(False)
        ctk.CTkLabel(rc, text="Port", font=("JetBrains Mono", 11), text_color=C["text_muted"]).pack(anchor="w", pady=(0, 2))
        self.e_port = ctk.CTkEntry(
            rc, height=36, fg_color=C["bg"], border_color=C["border"], text_color=C["text"], font=("JetBrains Mono", 13)
        )
        self.e_port.pack(fill="x")
        if p.get("port"):
            self.e_port.insert(0, str(p["port"]))

    def _build_tab_auth(self) -> None:
        t = self.tabs.tab("Авторизация")
        p = self.profile

        ctk.CTkLabel(
            t,
            text="Оставьте пустым если прокси без авторизации.",
            font=("JetBrains Mono", 11),
            text_color=C["text_dim"],
            justify="left",
        ).pack(anchor="w", padx=4, pady=(12, 4))

        self._lbl(t, "Логин")
        self.e_user = self._entry(t, p.get("username", ""))

        self._lbl(t, "Пароль")
        self.e_pwd = self._entry(t, p.get("password", ""), show="●")

        self.v_show = ctk.BooleanVar(value=False)

        def toggle_show() -> None:
            self.e_pwd.configure(show="" if self.v_show.get() else "●")

        ctk.CTkCheckBox(
            t,
            text="Показать пароль",
            variable=self.v_show,
            command=toggle_show,
            font=("JetBrains Mono", 11),
            text_color=C["text_muted"],
            fg_color=C["accent"],
            hover_color=C["accent2"],
            checkmark_color="#000",
        ).pack(anchor="w", padx=4, pady=(10, 0))

    def _build_tab_rules(self) -> None:
        t = self.tabs.tab("Правила")

        ctk.CTkLabel(
            t,
            text=(
                "Правила применяются сверху вниз — побеждает первое совпадение.\n"
                "Паттерн:  172.16.*.*   /   *.corp.local   /   10.0.0.0/8\n"
                "\"Напрямую\" — обход прокси.   \"Через прокси\" — форсировать."
            ),
            font=("JetBrains Mono", 10),
            text_color=C["text_dim"],
            justify="left",
            wraplength=500,
        ).pack(anchor="w", padx=4, pady=(10, 6))

        self._rules_container = ctk.CTkScrollableFrame(
            t, fg_color=C["bg"], border_color=C["border"], border_width=1, height=240
        )
        self._rules_container.pack(fill="both", expand=True, padx=4)
        self._render_rules()

        add_row = ctk.CTkFrame(t, fg_color="transparent")
        add_row.pack(fill="x", padx=4, pady=(8, 0))

        self.e_pat = ctk.CTkEntry(
            add_row,
            height=32,
            fg_color=C["bg"],
            border_color=C["border"],
            text_color=C["text"],
            font=("JetBrains Mono", 12),
            placeholder_text="172.16.*.*  /  *.example.com  /  10.0.0.0/8",
        )
        self.e_pat.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.v_act = ctk.StringVar(value="proxy")
        ctk.CTkOptionMenu(
            add_row,
            values=["proxy", "direct"],
            variable=self.v_act,
            fg_color=C["bg"],
            button_color=C["accent_dim"],
            button_hover_color=C["accent"],
            dropdown_fg_color=C["card"],
            text_color=C["text"],
            font=("JetBrains Mono", 11),
            width=100,
            height=32,
            dynamic_resizing=False,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            add_row,
            text="+ Добавить",
            width=90,
            height=32,
            fg_color=C["accent"],
            hover_color=C["accent2"],
            text_color="#000",
            font=("JetBrains Mono", 11, "bold"),
            command=self._add_rule,
        ).pack(side="left")

    def _render_rules(self) -> None:
        for w in self._rules_container.winfo_children():
            w.destroy()

        if not self._rules:
            ctk.CTkLabel(
                self._rules_container, text="Нет правил — весь трафик через прокси.", font=("JetBrains Mono", 11), text_color=C["text_dim"]
            ).pack(pady=20)
            return

        for i, rule in enumerate(self._rules):
            row = ctk.CTkFrame(self._rules_container, fg_color=C["card"], corner_radius=6)
            row.pack(fill="x", pady=(0, 4), padx=2)

            ctk.CTkLabel(row, text=f"#{i + 1}", font=("JetBrains Mono", 10), text_color=C["text_dim"], width=28).pack(
                side="left", padx=(8, 0)
            )
            ctk.CTkLabel(row, text=rule["pattern"], font=("JetBrains Mono", 12), text_color=C["text"]).pack(side="left", padx=8)

            action = rule.get("action", "proxy")
            act_color = C["accent"] if action == "proxy" else C["yellow"]
            act_label = "→ прокси" if action == "proxy" else "→ напрямую"
            ctk.CTkLabel(row, text=act_label, font=("JetBrains Mono", 11, "bold"), text_color=act_color).pack(side="left")

            idx = i
            ctk.CTkButton(
                row,
                text="✕",
                width=28,
                height=26,
                fg_color=C["red_dim"],
                hover_color="#5a2a2a",
                text_color=C["red"],
                font=("JetBrains Mono", 11),
                command=lambda i=idx: self._del_rule(i),
            ).pack(side="right", padx=(0, 6))
            if i < len(self._rules) - 1:
                ctk.CTkButton(
                    row,
                    text="↓",
                    width=28,
                    height=26,
                    fg_color=C["card_hover"],
                    hover_color=C["border"],
                    text_color=C["text_muted"],
                    font=("JetBrains Mono", 11),
                    command=lambda i=idx: self._move_rule(i, 1),
                ).pack(side="right", padx=(0, 2))
            if i > 0:
                ctk.CTkButton(
                    row,
                    text="↑",
                    width=28,
                    height=26,
                    fg_color=C["card_hover"],
                    hover_color=C["border"],
                    text_color=C["text_muted"],
                    font=("JetBrains Mono", 11),
                    command=lambda i=idx: self._move_rule(i, -1),
                ).pack(side="right", padx=(0, 2))

    def _add_rule(self) -> None:
        pat = self.e_pat.get().strip()
        if not pat:
            return
        self._rules.append({"pattern": pat, "action": self.v_act.get()})
        self.e_pat.delete(0, "end")
        self._render_rules()

    def _del_rule(self, idx: int) -> None:
        self._rules.pop(idx)
        self._render_rules()

    def _move_rule(self, idx: int, direction: int) -> None:
        ni = idx + direction
        if 0 <= ni < len(self._rules):
            self._rules[idx], self._rules[ni] = self._rules[ni], self._rules[idx]
        self._render_rules()

    def _save(self) -> None:
        name = self.e_name.get().strip()
        host = self.e_host.get().strip()
        ports = self.e_port.get().strip()

        if not name:
            messagebox.showerror("Ошибка", "Введите название.", parent=self)
            return
        if not host:
            messagebox.showerror("Ошибка", "Введите хост.", parent=self)
            return
        try:
            port = int(ports)
            assert 1 <= port <= 65535
        except Exception:
            messagebox.showerror("Ошибка", "Порт 1–65535.", parent=self)
            return

        data = {
            "name": name,
            "type": self.v_type.get(),
            "host": host,
            "port": port,
            "username": self.e_user.get().strip(),
            "password": self.e_pwd.get(),
            "rules": self._rules,
        }
        if self.on_save:
            self.on_save(data)
        self.destroy()


class ProfileCard(ctk.CTkFrame):
    def __init__(
        self, master: Any, profile: Dict[str, Any], is_active: bool, on_activate: Callable, on_edit: Callable, on_delete: Callable, on_test: Callable
    ) -> None:
        bc = C["border_act"] if is_active else C["border"]
        bg = C["card_active"] if is_active else C["card"]
        super().__init__(master, fg_color=bg, corner_radius=10, border_width=1, border_color=bc)
        self.profile: Dict[str, Any] = profile
        self.is_active = is_active
        self.on_activate = on_activate
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_test = on_test
        self._build()

    def _build(self) -> None:
        p = self.profile
        tc, bc = TYPE_BADGE.get(p["type"], (C["text"], C["card_hover"]))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))

        self._dot = ctk.CTkLabel(top, text="●", font=("Arial", 13), text_color=S_DOT[S_IDLE], width=18)
        self._dot.pack(side="left")

        ctk.CTkLabel(top, text=p["name"], font=("JetBrains Mono", 13, "bold"), text_color=C["text"]).pack(side="left", padx=(6, 0))

        b = ctk.CTkFrame(top, fg_color=bc, corner_radius=4)
        b.pack(side="left", padx=8)
        ctk.CTkLabel(b, text=p["type"], font=("JetBrains Mono", 9, "bold"), text_color=tc, padx=5, pady=1).pack()

        if p.get("username"):
            ab = ctk.CTkFrame(top, fg_color=C["yellow_dim"], corner_radius=4)
            ab.pack(side="left", padx=(0, 6))
            ctk.CTkLabel(ab, text="AUTH", font=("JetBrains Mono", 9, "bold"), text_color=C["yellow"], padx=5, pady=1).pack()

        n = len(p.get("rules", []))
        if n:
            rb = ctk.CTkFrame(top, fg_color=C["accent_dim"], corner_radius=4)
            rb.pack(side="left")
            ctk.CTkLabel(rb, text=f"{n} правил", font=("JetBrains Mono", 9), text_color=C["accent"], padx=5, pady=1).pack()

        if self.is_active:
            ctk.CTkLabel(top, text="▶ АКТИВЕН", font=("JetBrains Mono", 10, "bold"), text_color=C["green"]).pack(side="right")

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=14, pady=(0, 10))

        self._info = ctk.CTkLabel(bot, text=f"{p['host']}:{p['port']}", font=("JetBrains Mono", 11), text_color=C["text_muted"])
        self._info.pack(side="left")

        for lbl, fg, hv, tc2, cmd in [
            ("✎ Изменить", C["card_hover"], "#2d333b", C["text_muted"], lambda: self.on_edit(self.profile)),
            ("✕ Удалить", C["red_dim"], "#5a2a2a", C["red"], lambda: self.on_delete(self.profile)),
            ("⟳ Проверить", C["card_hover"], "#2d333b", C["text_muted"], lambda: self.on_test(self.profile, self)),
        ]:
            ctk.CTkButton(
                bot,
                text=lbl,
                height=26,
                width=90,
                fg_color=fg,
                hover_color=hv,
                text_color=tc2,
                font=("JetBrains Mono", 10),
                corner_radius=6,
                command=cmd,
            ).pack(side="right", padx=(4, 0))

        if not self.is_active:
            ctk.CTkButton(
                bot,
                text="▶ Применить",
                height=26,
                width=96,
                fg_color=C["accent"],
                hover_color=C["accent2"],
                text_color="#000",
                font=("JetBrains Mono", 10, "bold"),
                corner_radius=6,
                command=lambda: self.on_activate(self.profile),
            ).pack(side="right", padx=(4, 0))

    def set_status(self, status: str, latency: float = 0.0) -> None:
        p = self.profile
        color = S_DOT.get(status, C["text_dim"])
        if status == S_OK:
            txt = f"{p['host']}:{p['port']}  ·  {latency} ms ✔"
        elif status == S_FAIL:
            txt = f"{p['host']}:{p['port']}  ·  недоступен ✘"
        elif status == S_TESTING:
            txt = f"{p['host']}:{p['port']}  ·  проверка…"
        else:
            txt = f"{p['host']}:{p['port']}"
        try:
            self._dot.configure(text_color=color)
            self._info.configure(text=txt)
        except Exception:
            pass


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.store = ProfileStore()
        self._cards: Dict[str, ctk.CTkFrame] = {}
        self._routing_proxy: Optional[RoutingProxy] = None

        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry("720x640")
        self.minsize(580, 420)
        self.configure(fg_color=C["bg"])

        self._build_header()
        self._build_statusbar()
        self._build_body()
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=C["panel"], height=60, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        inner = ctk.CTkFrame(hdr, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20)

        ctk.CTkLabel(inner, text="⬡  ProxySwitch", font=("JetBrains Mono", 17, "bold"), text_color=C["accent"]).pack(
            side="left", pady=14
        )

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(side="right", pady=12)

        ctk.CTkButton(
            btns,
            text="📝 Логи",
            fg_color=C["card_hover"],
            hover_color="#2d333b",
            text_color=C["text_muted"],
            font=("JetBrains Mono", 12),
            height=34,
            corner_radius=8,
            command=self._open_logs,
        ).pack(side="right", padx=(0, 6))

        ctk.CTkButton(
            btns,
            text="⊘ Отключить",
            fg_color=C["red_dim"],
            hover_color="#5a2a2a",
            text_color=C["red"],
            font=("JetBrains Mono", 12),
            height=34,
            corner_radius=8,
            command=self._disable_proxy,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btns,
            text="+ Профиль",
            fg_color=C["accent"],
            hover_color=C["accent2"],
            text_color="#000",
            font=("JetBrains Mono", 13, "bold"),
            height=34,
            corner_radius=8,
            command=self._open_add,
        ).pack(side="right")

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=C["panel"], height=32, corner_radius=0)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self._status_lbl = ctk.CTkLabel(bar, text="Прокси не активен", font=("JetBrains Mono", 10), text_color=C["text_dim"])
        self._status_lbl.pack(side="left", padx=18)

        self._rp_lbl = ctk.CTkLabel(bar, text="", font=("JetBrains Mono", 10), text_color=C["text_dim"])
        self._rp_lbl.pack(side="right", padx=18)

    def _build_body(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(14, 6))

        ctk.CTkLabel(hdr, text="ПРОФИЛИ", font=("JetBrains Mono", 10, "bold"), text_color=C["text_dim"]).pack(side="left")
        self._count_lbl = ctk.CTkLabel(hdr, text="", font=("JetBrains Mono", 10), text_color=C["text_dim"])
        self._count_lbl.pack(side="left", padx=8)

        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
        )
        self._scroll.pack(fill="both", expand=True, padx=20, pady=(0, 16))

    def _refresh(self) -> None:
        for w in self._scroll.winfo_children():
            w.destroy()
        self._cards.clear()

        n = len(self.store.profiles)
        self._count_lbl.configure(text=f"({n})" if n else "")

        if not n:
            ctk.CTkLabel(
                self._scroll,
                text="Нет профилей — нажмите «+ Профиль» чтобы добавить.",
                font=("JetBrains Mono", 12),
                text_color=C["text_dim"],
            ).pack(pady=60)
            return

        for p in self.store.profiles:
            card = ProfileCard(
                self._scroll,
                p,
                is_active=(p["id"] == self.store.active_id),
                on_activate=self._activate,
                on_edit=self._open_edit,
                on_delete=self._delete,
                on_test=self._test_proxy,
            )
            card.pack(fill="x", pady=(0, 8))
            self._cards[p["id"]] = card

    def _activate(self, profile: Dict[str, Any]) -> None:
        system_proxy_set = False
        try:
            if self._routing_proxy:
                try:
                    self._routing_proxy.stop()
                except Exception as e:
                    logger.warning(f"Error stopping previous routing proxy: {e}")
                self._routing_proxy = None

            rp = RoutingProxy(profile)
            rp.start()
            self._routing_proxy = rp
            logger.info(f"Started routing proxy for profile {profile['name']}")

            ok_upstream, upstream_lat, upstream_err = test_proxy(profile)
            if not ok_upstream:
                raise RuntimeError(f"Верхний прокси недоступен: {upstream_err}")

            direct = [r["pattern"] for r in profile.get("rules", []) if r.get("action") == "direct"]

            ok, msg = set_system_proxy_to_local(direct)
            if not ok:
                raise RuntimeError(msg)
            system_proxy_set = True

            local_ok, local_lat, local_err = test_local_proxy()
            if not local_ok:
                raise RuntimeError(f"Системный прокси установлен, но локальный routing не работает: {local_err}")

            self.store.set_active(profile["id"])
            n = len(profile.get("rules", []))
            rules_txt = f"  ·  {n} правил" if n else ""
            auth_txt = f"  ·  auth" if profile.get("username") else ""
            self._status_lbl.configure(
                text=(
                    f"▶  {profile['name']}  ({profile['type']} · {profile['host']}:{profile['port']})"
                    f"{auth_txt}{rules_txt}  ·  up {upstream_lat} ms  ·  local {local_lat} ms"
                ),
                text_color=C["green"],
            )
            self._rp_lbl.configure(text=f"routing 127.0.0.1:{LOCAL_PROXY_PORT}", text_color=C["accent"])

            self._refresh()
        except Exception as e:
            logger.exception("Error activating profile")
            if self._routing_proxy:
                try:
                    self._routing_proxy.stop()
                except Exception:
                    pass
            self._routing_proxy = None
            if system_proxy_set:
                clear_system_proxy()
            self.store.set_active(None)
            self._status_lbl.configure(text=f"✘  {e}", text_color=C["red"])
            self._rp_lbl.configure(text="")
            self._refresh()
            messagebox.showerror("Ошибка", f"Профиль не активирован: {e}")

    def _disable_proxy(self) -> None:
        try:
            if self._routing_proxy:
                try:
                    self._routing_proxy.stop()
                except Exception as e:
                    logger.warning(f"Error stopping routing proxy: {e}")
                self._routing_proxy = None
            ok, msg = clear_system_proxy()
            self.store.set_active(None)
            if ok:
                self._status_lbl.configure(text="Прокси отключён.", text_color=C["text_muted"])
            else:
                self._status_lbl.configure(text=f"✘ Не удалось отключить: {msg}", text_color=C["red"])
            self._rp_lbl.configure(text="")
            logger.info("Proxy disabled")
            self._refresh()
        except Exception as e:
            logger.exception("Error disabling proxy")
            messagebox.showerror("Ошибка", f"Ошибка отключения прокси: {e}")

    def _open_logs(self) -> None:
        log_path = self.store.path.parent / "debug.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if not log_path.exists():
                log_path.touch()

            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(log_path)])
            elif platform.system() == "Windows":
                subprocess.Popen(["cmd", "/c", "start", "", str(log_path)], shell=False)
            else:
                subprocess.Popen(["xdg-open", str(log_path)])
            logger.info(f"Opened log file: {log_path}")
        except Exception as e:
            logger.exception("Error opening log file")
            messagebox.showerror("Ошибка", f"Не удалось открыть лог: {e}")

    def _open_add(self) -> None:
        def save(data: Dict[str, Any]) -> None:
            self.store.add(data)
            self._refresh()

        ProfileDialog(self, on_save=save)

    def _open_edit(self, profile: Dict[str, Any]) -> None:
        def save(data: Dict[str, Any]) -> None:
            self.store.update(profile["id"], data)
            if self.store.active_id == profile["id"]:
                updated = self.store.get(profile["id"])
                if updated:
                    self._activate(updated)
                    return
            self._refresh()

        ProfileDialog(self, profile=profile, on_save=save)

    def _delete(self, profile: Dict[str, Any]) -> None:
        if messagebox.askyesno("Удалить профиль", f"Удалить «{profile['name']}»?"):
            if self.store.active_id == profile["id"]:
                self._disable_proxy()
            self.store.delete(profile["id"])
            self._refresh()

    def _test_proxy(self, profile: Dict[str, Any], card: ProfileCard) -> None:
        card.set_status(S_TESTING)

        def _run() -> None:
            ok, lat, err = test_proxy(profile)
            if not ok:
                logger.warning(f"Manual proxy test failed for '{profile.get('name', 'unknown')}': {err}")
            self.after(0, lambda: card.set_status(S_OK if ok else S_FAIL, lat))

        threading.Thread(target=_run, daemon=True).start()

    def _on_close(self) -> None:
        try:
            if self._routing_proxy:
                try:
                    self._routing_proxy.stop()
                except Exception as e:
                    logger.warning(f"Error stopping proxy on close: {e}")
            self.destroy()
            logger.info("Application closed")
        except Exception:
            logger.exception("Error on close")
            try:
                self.destroy()
            except Exception:
                pass
