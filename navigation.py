"""Home and settings navigation for the three-button interface."""

from dataclasses import replace

HOME_ITEMS = ("WORKOUT", "SETTINGS")
SETTING_ITEMS = (
    ("BRIGHTNESS", "brightness", 10),
    ("SOUND", "sound", 1),
    ("BACK", None, 0),
)


class Navigation:
    def __init__(self):
        self.screen = "home"
        self.home_index = 0
        self.settings_index = 0
        self.editing = False
        self.select_index = 0
        self.error = None

    def button(self, event, session, settings, save):
        self.error = None
        if event == "hold":
            session.standby()
            self.screen = "standby"
            self.editing = False
            return settings
        if self.screen == "standby":
            if event == "ok":
                session.confirm(0)
                self.screen = "home"
            return settings
        delta = -1 if event == "prev" else 1
        if self.screen == "home":
            if event in ("prev", "next"):
                self.home_index = (self.home_index + delta) % len(HOME_ITEMS)
            elif event == "ok":
                self.screen = "select" if self.home_index == 0 else "settings"
                self.select_index = session.choice
        elif self.screen == "select":
            if event in ("prev", "next"):
                self.select_index = (self.select_index + delta) % (len(session.workouts) + 1)
                if self.select_index < len(session.workouts):
                    session.choice = self.select_index
            elif event == "ok":
                if self.select_index == len(session.workouts):
                    self.screen = "home"
                else:
                    self.screen = "workout"
        elif self.screen == "settings":
            if event in ("prev", "next") and not self.editing:
                self.settings_index = (self.settings_index + delta) % len(SETTING_ITEMS)
            elif event in ("prev", "next"):
                _, field, step = SETTING_ITEMS[self.settings_index]
                value = getattr(settings, field)
                value = not value if field == "sound" else round(value + delta * step, 2)
                try:
                    candidate = replace(settings, **{field: value})
                    save(candidate)
                except (ValueError, OSError) as exc:
                    self.error = str(exc)
                else:
                    return candidate
            elif event == "ok":
                if SETTING_ITEMS[self.settings_index][1] is None:
                    self.screen = "home"
                else:
                    self.editing = not self.editing
        return settings
