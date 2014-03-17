import os
import time
import struct
import binascii
import plistlib
import threading

import sublime
import sublime_plugin

appdata_path = os.path.split(sublime.packages_path())[0]
cache_path = os.path.join(sublime.packages_path(), 'User', 'Pulse')
pulsing_views = {}


def hex_to_rgb(hex):
    return struct.unpack('BBB', bytes.fromhex(hex[1:]))


def rgb_to_hex(r, g, b):
    return '#' + binascii.hexlify(struct.pack('BBB', r, g, b)).decode('ascii')


def _decrement_positive_integer(value):
    if value:
        return value - 1
    return value


class PulseEventListener(sublime_plugin.EventListener):

    def on_close(self, view):
        id_ = view.id()
        if not id_ in pulsing_views:
            return
        pulsing_views[id_].stop()
        del pulsing_views[id_]


class PulseThread(threading.Thread):

    def __init__(self, changes, delay, pause):
        threading.Thread.__init__(self)
        self.changes = changes
        self.reversed_changes = changes[::-1]
        self.delay = delay
        self.pause = pause
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            for change in self.changes:
                change()
                time.sleep(self.delay)
            time.sleep(self.pause)

            for change in self.reversed_changes:
                change()
                time.sleep(self.delay)
            time.sleep(self.pause)

    def stop(self):
        self._stop.set()


class PulseCommand(sublime_plugin.TextCommand):

    def run(self, edit, delta=25, delay=0.05, pause=0.5, stop=False):
        view_id = self.view.id()
        if view_id in pulsing_views:
            if stop:
                pulsing_views[view_id].stop()
                del pulsing_views[view_id]
            return

        view_settings = self.view.settings()
        color_scheme_relative_path = view_settings.get('color_scheme')

        color_scheme_path = os.path.join(appdata_path, os.path.normpath(color_scheme_relative_path))
        print(appdata_path)
        print(color_scheme_relative_path)
        print(color_scheme_path)
        theme = plistlib.readPlist(color_scheme_path)

        background_settings = []
        for setting in theme['settings']:
            if not 'scope' in setting:
                background_settings.append(setting['settings'])
                continue

            if setting['scope'] == 'text' or setting['scope'].startswith('source.'):
                background_settings.append(setting['settings'])

        if not os.path.isdir(cache_path):
            os.makedirs(cache_path)

        rgb_is_zero = False
        changes = [lambda: view_settings.set('color_scheme', color_scheme_relative_path)]
        for index in range(delta):
            if rgb_is_zero:
                break

            for background_setting in background_settings:
                r, g, b = hex_to_rgb(background_setting['background'])
                if all(not value for value in (r, g, b)):
                    rgb_is_zero = True
                    break
                r, g, b = list(map(_decrement_positive_integer, [r, g, b]))
                background_setting['background'] = rgb_to_hex(r, g, b)

            path = os.path.join(cache_path, str(index) + '.tmTheme')
            plistlib.writePlist(theme, path)
            relative_path = os.path.relpath(path, appdata_path).replace('\\', '/')

            def change_color_scheme_function(relative_path):
                def function():
                    view_settings.set('color_scheme', relative_path)
                return function

            changes.append(change_color_scheme_function(relative_path))

        thread = PulseThread(changes, delay, pause)
        pulsing_views[view_id] = thread
        thread.start()
