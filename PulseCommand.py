import binascii
import os
import plistlib
import struct
import threading
import time
import zipfile

import sublime
import sublime_plugin

pulsing_views = {}


def hex_to_rgb(hex):
    return struct.unpack('BBB', bytes.fromhex(hex[1:]))


def rgb_to_hex(r, g, b):
    return '#' + binascii.hexlify(struct.pack('BBB', r, g, b)).decode('ascii')


def extract_from_package(member_path, path):
    path_segments = member_path.split('/')
    package_name = path_segments[1]

    sublime_text_appdata_path = os.path.dirname(sublime.packages_path())
    package_path = os.path.join(sublime_text_appdata_path, 'Installed Packages', package_name + '.sublime-package')

    with zipfile.ZipFile(package_path) as file_:
        file_.extract('/'.join(path_segments[2:]), path)


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
        if stop:
            if view_id in pulsing_views:
                pulsing_views[view_id].stop()
                del pulsing_views[view_id]
            return

        sublime_text_packages_path = sublime.packages_path()
        sublime_text_appdata_path = os.path.dirname(sublime_text_packages_path)
        view_settings = self.view.settings()
        color_scheme_relative_path = view_settings.get('color_scheme')
        color_scheme_path = os.path.join(sublime_text_appdata_path, os.path.normpath(color_scheme_relative_path))

        # Contained within installed package
        if not os.path.exists(color_scheme_path):
            path_segments = color_scheme_relative_path.split('/')
            extraction_path = os.path.join(sublime_text_packages_path, os.path.join(*path_segments[1:-1]))
            if not os.path.exists(extraction_path):
                os.makedirs(extraction_path)

            extract_from_package(color_scheme_relative_path, extraction_path)

        theme = plistlib.readPlist(color_scheme_path)
        background_settings = []
        for setting in theme['settings']:
            if not 'scope' in setting:
                background_settings.append(setting['settings'])
                continue

            if setting['scope'] == 'text' or setting['scope'].startswith('source.'):
                background_settings.append(setting['settings'])

        cache_path = os.path.join(sublime_text_packages_path, 'User', 'Pulse')
        if not os.path.isdir(cache_path):
            os.makedirs(cache_path)

        rgb_is_zero = False
        changes = [lambda: view_settings.set('color_scheme', color_scheme_relative_path)]
        for index in range(delta):
            if rgb_is_zero:
                break

            for background_setting in background_settings:
                r, g, b = hex_to_rgb(background_setting['background'])
                if all(value == 0 for value in (r, g, b)):
                    rgb_is_zero = True
                    break

                r, g, b = list(map(lambda value: value - 1 if value > 0 else value, [r, g, b]))
                background_setting['background'] = rgb_to_hex(r, g, b)

            path = os.path.join(cache_path, str(index) + '.tmTheme')
            plistlib.writePlist(theme, path)
            relative_path = os.path.relpath(path, sublime_text_appdata_path).replace('\\', '/')

            def make_change_color_scheme_function(relative_path):
                def function():
                    view_settings.set('color_scheme', relative_path)
                return function

            changes.append(make_change_color_scheme_function(relative_path))

        thread = PulseThread(changes, delay, pause)
        pulsing_views[view_id] = thread
        thread.start()
