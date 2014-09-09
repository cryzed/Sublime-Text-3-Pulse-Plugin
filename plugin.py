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
BLACK_ARGB = (100, 0, 0, 0)

pulsing_views = {}


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


def hex_string_to_argb(hex_string):
    if len(hex_string) == 7:
        return (100,) + struct.unpack('BBB', bytes.fromhex(hex_string[1:]))
    return struct.unpack('BBBB', bytes.fromhex(hex_string[1:]))


def argb_to_hex_string(a, r, g, b):
    if a == 100:
        return '#' + binascii.hexlify(struct.pack('BBB', r, g, b)).decode('ASCII')
    return '#' + binascii.hexlify(struct.pack('BBBB', a, r, g, b)).decode('ASCII')


def make_settings_path(path):
    return os.path.relpath(path, APPDATA_PATH).replace('\\', '/')


def make_change_color_scheme_function(settings, path):
    return lambda: settings.set('color_scheme', path)


def pulse_view(view_id, changes, delay, pause):
    current_delay = 0
    maximum_delay = delay * len(changes) * 2

    for change in changes:
        sublime.set_timeout(change, current_delay)
        reverse_delay = maximum_delay - current_delay

        # Don't queue the same callback twice at the curve's peak
        if reverse_delay != current_delay:
            sublime.set_timeout(change, reverse_delay)

        current_delay += delay

    if pulsing_views[view_id]['enabled']:
        sublime.set_timeout(lambda: pulse_view(view_id, changes, delay, pause), maximum_delay + pause)
    else:
        cleanup_pulsing_view(view_id)


def cleanup_pulsing_view(view_id):
    pulsing_views[view_id]['change_original_color_scheme']()
    shutil.rmtree(get_cache_path(str(view_id)))
    del pulsing_views[view_id]


class TogglePulseViewEventListener(sublime_plugin.EventListener):
    def on_close(self, view):
        view_id = view.id()
        if view_id in pulsing_views:
            cleanup_pulsing_view(view_id)


class TogglePulseViewCommand(sublime_plugin.TextCommand):
    def __init__(self, *args, **kwargs):
        sublime_plugin.TextCommand.__init__(self, *args, **kwargs)
        self.run = wrap_async_function(self.run)

    def run(self, edit, delta, delay, pause):
        view_id = self.view.id()
        if view_id in pulsing_views and pulsing_views[view_id]['enabled']:
            pulsing_views[view_id]['enabled'] = False
            return

        view_settings = self.view.settings()
        original_color_scheme_settings_path = view_settings.get('color_scheme')
        property_list = plistlib.readPlistFromBytes(sublime.load_binary_resource(original_color_scheme_settings_path))

        background_settings = []
        for setting in property_list['settings']:
            settings = setting['settings']
            if 'background' in settings:
                background_settings.append(settings)

        view_cache_path = get_cache_path(str(view_id))
        change_original_color_scheme = make_change_color_scheme_function(view_settings, original_color_scheme_settings_path)
        changes = [change_original_color_scheme]
        is_black = False
        for difference in range(delta):
            if is_black:
                break

            for setting in background_settings:
                a, r, g, b = hex_string_to_argb(setting['background'])
                r, g, b = tuple(map(lambda value: value - 1 if value > 0 else value, (r, g, b)))
                setting['background'] = argb_to_hex_string(a, r, g, b)
                is_black = (a, r, g, b) == BLACK_ARGB
                if is_black:
                    break

            color_scheme_cache_path = os.path.join(view_cache_path, str(difference))
            plistlib.writePlist(property_list, color_scheme_cache_path)
            changes.append(make_change_color_scheme_function(view_settings, make_settings_path(color_scheme_cache_path)))

        pulsing_views[view_id] = {'enabled': True, 'change_original_color_scheme': change_original_color_scheme}
        pulse_view(view_id, changes, delay * 1000, pause * 1000)
