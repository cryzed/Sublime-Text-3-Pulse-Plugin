import binascii
import os
import plistlib
import shutil
import struct
import threading
import time
import zipfile

import sublime
import sublime_plugin

PACKAGES_PATH = None
APPDATA_PATH = None
CACHE_PATH = None

pulsing_views = {}


def plugin_loaded():
    global PACKAGES_PATH
    global APPDATA_PATH
    global CACHE_PATH

    PACKAGES_PATH = sublime.packages_path()
    APPDATA_PATH = os.path.dirname(PACKAGES_PATH)
    CACHE_PATH = os.path.join(PACKAGES_PATH, 'User', 'Pulse.cache')

    if os.path.exists(CACHE_PATH):
        shutil.rmtree(CACHE_PATH)

    os.makedirs(CACHE_PATH)


def extract_from_package(member_path, path):
    path_segments = member_path.split('/')
    package_name = path_segments[1]
    package_path = os.path.join(APPDATA_PATH, 'Installed Packages', package_name + '.sublime-package')

    with zipfile.ZipFile(package_path) as file_:
        file_.extract('/'.join(path_segments[2:]), path)


def hex_to_rgb(hex):
    return struct.unpack('BBB', bytes.fromhex(hex[1:]))


def rgb_to_hex(r, g, b):
    return '#' + binascii.hexlify(struct.pack('BBB', r, g, b)).decode('ascii')


def make_change_view_color_scheme_function(view_settings, sublime_text_color_scheme_path):
    return lambda: view_settings.set('color_scheme', sublime_text_color_scheme_path)


def stop_pulsing_view(view_id):
    if not view_id in pulsing_views:
        return

    pulsing_views[view_id].stop()
    del pulsing_views[view_id]

    shutil.rmtree(os.path.join(CACHE_PATH, str(view_id)))


class PulseEventListener(sublime_plugin.EventListener):

    def on_close(self, view):
        view_id = view.id()
        if view_id in pulsing_views:
            stop_pulsing_view(view_id)


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
        if stop and view_id in pulsing_views:
            stop_pulsing_view(view_id)
            return

        view_settings = self.view.settings()
        sublime_text_color_scheme_path = view_settings.get('color_scheme')
        color_scheme_path = os.path.join(APPDATA_PATH, os.path.normpath(sublime_text_color_scheme_path))

        if not os.path.exists(color_scheme_path):
            path_segments = sublime_text_color_scheme_path.split('/')
            extraction_path = os.path.join(PACKAGES_PATH, *path_segments[1:-1])
            if not os.path.exists(extraction_path):
                os.makedirs(extraction_path)

            extract_from_package(sublime_text_color_scheme_path, extraction_path)

        theme = plistlib.readPlist(color_scheme_path)
        background_settings = []
        for setting in theme['settings']:
            if not 'scope' in setting:
                background_settings.append(setting['settings'])
                continue

            if setting['scope'] == 'text' or setting['scope'].startswith('source.'):
                background_settings.append(setting['settings'])

        cache_path = os.path.join(CACHE_PATH, str(view_id))
        if not os.path.isdir(cache_path):
            os.makedirs(cache_path)

        rgb_is_zero = False
        changes = [make_change_view_color_scheme_function(view_settings, sublime_text_color_scheme_path)]
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

            color_scheme_cache_path = os.path.join(cache_path, str(index))
            plistlib.writePlist(theme, color_scheme_cache_path)
            new_sublime_text_color_scheme_path = os.path.relpath(color_scheme_cache_path, APPDATA_PATH).replace('\\', '/')
            changes.append(make_change_view_color_scheme_function(view_settings, new_sublime_text_color_scheme_path))

        pulse_thread = PulseThread(changes, delay, pause)
        pulsing_views[view_id] = pulse_thread
        pulse_thread.start()
