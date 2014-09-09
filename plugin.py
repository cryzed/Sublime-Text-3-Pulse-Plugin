import sublime
import sublime_plugin

import binascii
import functools
import os
import plistlib
import shutil
import struct

APPDATA_PATH = None
CACHE_PATH = None
BLACK_RGB = (0, 0, 0)

pulsing_views = set()


def plugin_loaded():
    global APPDATA_PATH
    global CACHE_PATH

    packages_path = sublime.packages_path()
    APPDATA_PATH = os.path.dirname(packages_path)
    CACHE_PATH = os.path.join(packages_path, 'User', 'Pulse.cache')

    if os.path.exists(CACHE_PATH):
        shutil.rmtree(CACHE_PATH)

    os.makedirs(CACHE_PATH)


def wrap_async_function(function):
    @functools.wraps(function)
    def async_function(*args, **kwargs):
        sublime.set_timeout_async(lambda: function(*args, **kwargs), 0)

    return async_function


def get_cache_path(key):
    cache_path = os.path.join(CACHE_PATH, key)
    if not os.path.exists(cache_path):
        os.makedirs(cache_path)

    return cache_path


def hex_string_to_rgb(hex_string):
    return struct.unpack('BBB', bytes.fromhex(hex_string[1:]))


def rgb_to_hex_string(r, g, b):
    return '#' + binascii.hexlify(struct.pack('BBB', r, g, b)).decode('ASCII')


def make_settings_path(path):
    return os.path.relpath(path, APPDATA_PATH).replace('\\', '/')


def make_change_color_scheme_function(settings, path):
    return lambda: settings.set('color_scheme', path)


def pulse_view(view_id, changes, delay, pause):
    current_delay = 0
    maximum_delay = delay * len(changes) * 2

    for change in changes:
        sublime.set_timeout_async(change, current_delay)
        reverse_delay = maximum_delay - current_delay

        # Don't queue the same callback twice at the curve's peak
        if reverse_delay != current_delay:
            sublime.set_timeout_async(change, reverse_delay)

        current_delay += delay

    if view_id in pulsing_views:
        sublime.set_timeout_async(lambda: pulse_view(view_id, changes, delay, pause), maximum_delay + pause)


class TogglePulseViewEventListener(sublime_plugin.EventListener):
    def on_close(self, view):
        view_id = view.id()
        if view_id in pulsing_views:
            pulsing_views.remove(view_id)


class TogglePulseViewCommand(sublime_plugin.TextCommand):
    def __init__(self, *args, **kwargs):
        sublime_plugin.TextCommand.__init__(self, *args, **kwargs)
        self.run = wrap_async_function(self.run)

    def run(self, edit, delta, delay, pause):
        view_id = self.view.id()
        if view_id in pulsing_views:
            pulsing_views.remove(view_id)
            return

        view_settings = self.view.settings()
        property_list = plistlib.readPlistFromBytes(sublime.load_binary_resource(view_settings.get('color_scheme')))

        background_settings = []
        for setting in property_list['settings']:
            settings = setting['settings']
            if 'background' in settings:
                background_settings.append(settings)

        view_cache_path = get_cache_path(str(view_id))
        original_color_scheme_cache_path = os.path.join(view_cache_path, '0')
        plistlib.writePlist(property_list, original_color_scheme_cache_path)
        changes = [make_change_color_scheme_function(view_settings, make_settings_path(original_color_scheme_cache_path))]

        is_black = False
        for difference in range(1, delta + 1):
            if is_black:
                break

            for setting in background_settings:
                rgb = hex_string_to_rgb(setting['background'])
                rgb = tuple(map(lambda value: value - 1 if value > 0 else value, rgb))
                setting['background'] = rgb_to_hex_string(*rgb)
                is_black = rgb == BLACK_RGB
                if is_black:
                    break

            color_scheme_cache_path = os.path.join(view_cache_path, str(difference))
            plistlib.writePlist(property_list, color_scheme_cache_path)
            changes.append(make_change_color_scheme_function(view_settings, make_settings_path(color_scheme_cache_path)))

        pulsing_views.add(view_id)
        pulse_view(view_id, changes, delay * 1000, pause * 1000)
