#!/usr/bin/python
# coding=UTF-8

# Copyright 2008 Gary C. Martin
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#
# Activity web site: http://wiki.laptop.org/go/Moon
# Created: Febuary 2008
# Author: gary@garycmartin.com
# Home page: http://www.garycmartin.com/

"""Moon phase information XO activity.

Basic activity displaying Luna phase and related information. Calculations are
based on an internal look-up table generated from a public NASA source. No
network connection is needed.
"""

import gtk
import gobject
from sugar.activity import activity
from sugar.graphics.toggletoolbutton import ToggleToolButton
from sugar.graphics.toolbutton import ToolButton
from sugar import profile
from sugar.datastore import datastore
from gettext import gettext as _
import math
import time
import os

try:
    import json
    json.dumps
except (ImportError, AttributeError):
    import simplejson as json

from sugar.graphics.toolbarbox import ToolbarButton, ToolbarBox
from sugar.activity.widgets import ActivityToolbarButton
from sugar.activity.widgets import StopButton

IMAGE_SIZE = 726
HALF_SIZE = IMAGE_SIZE / 2
ECLIPSE_TYPES = {
    'T' : _('Total'),
    'A' : _('Annular'),
    'H' : _('Hybrid'),
    'P' : _('Partial'),
    't' : _('Total'),
    'p' : _('Partial'),
    'n' : _('Penumbral')
}

# TRANS: Date format for next full/new moon and next solar/lunar eclipse
LOCALE_DATE_FORMAT = _("%c")

class MoonActivity(activity.Activity):
    """Moon phase activity.
    """
    def __init__(self, handle):
        activity.Activity.__init__(self, handle)
        self._name = handle
        self.set_title(_("Moon"))
        
        # Defaults (Resume priority, persistent file secondary, fall-back hardcoded)
        self.hemisphere_view = 'north'
        self.show_grid = False
        self.activity_state = {}
        self.activity_state['hemisphereView'] = self.hemisphere_view
        self.activity_state['showGrid'] = self.show_grid
        self.read_and_parse_prefs(self.get_activity_root() + '/data/defaults')
                
        # Toolbox
        try:
            # Use new >= 0.86 toolbar design
            self.max_participants = 1
            toolbar_box = ToolbarBox()
            activity_button = ActivityToolbarButton(self)
            toolbar_box.toolbar.insert(activity_button, 0)
            separator = gtk.SeparatorToolItem()
            toolbar_box.toolbar.insert(separator, -1)
            self.toggle_grid_button = ToggleToolButton('grid-icon')
            self.toggle_grid_button.set_tooltip(_("Toggle Grid View"))
            self.toggle_grid_button.set_active(self.show_grid)
            self.toggle_grid_handler_id = self.toggle_grid_button.connect('clicked', self.toggle_grid_clicked)
            toolbar_box.toolbar.insert(self.toggle_grid_button, -1)
            self.toggle_grid_button.show()
            self.toggle_hemisphere_button = ToggleToolButton('hemi-icon')
            self.toggle_hemisphere_button.set_tooltip(_("Toggle Hemisphere View"))
            self.toggle_hemisphere_button.set_active(self.hemisphere_view == 'south')
            self.toggle_hemisphere_handler_id = self.toggle_hemisphere_button.connect('clicked', self.toggle_hemisphere_clicked)
            toolbar_box.toolbar.insert(self.toggle_hemisphere_button, -1)
            self.toggle_hemisphere_button.show()

            self.image_button = ToolButton('save-image')
            self.image_button.set_tooltip(_("Save As Image"))
            self.image_button.connect('clicked', self.save_image)
            toolbar_box.toolbar.insert(self.image_button, -1)
            self.image_button.show()

            separator = gtk.SeparatorToolItem()
            separator.props.draw = False
            separator.set_expand(True)
            separator.show()
            toolbar_box.toolbar.insert(separator, -1)

            tool = StopButton(self)
            toolbar_box.toolbar.insert(tool, -1)
            self.set_toolbox(toolbar_box)
            toolbar_box.show()

        except NameError:
            pass

        # Items we don't have to do every redraw
        colormap = gtk.gdk.colormap_get_system()
        self.black_alloc_color = colormap.alloc_color('black')
        self.white_alloc_color = colormap.alloc_color('white')
        self.blue_green_mask_alloc_color = colormap.alloc_color('#F00')
        self.red_alloc_color = colormap.alloc_color('#F20')
        self.blue_alloc_color = colormap.alloc_color('#04F')
        self.moon_stamp = gtk.gdk.pixbuf_new_from_file("moon.jpg")
        self.image_size_cache = -1

        # Build main layout manually for the first pass
        self.build_main_layout_cb()

        # Watch for signal that the screen changed size (landscape vs. portrait)
        gtk.gdk.screen_get_default().connect('size-changed', self.build_main_layout_cb)

    def build_main_layout_cb(self, widget=None, data=None):
        """Create main layout respecting landscape or portrait orientation.
        """

        # Create event box to hold Moon image (so I can set background color)
        info_scroll = gtk.ScrolledWindow()
        self.event_box = gtk.EventBox()

        # Create the main activity layout
        if self.is_landscape_orientation():
            self.main_view = gtk.HBox()
            self.info_panel = gtk.VBox()
            self.event_box.set_size_request(int(gtk.gdk.screen_width() / 1.70), -1)
            self.main_view.pack_end(self.event_box, False)
            self.main_view.pack_start(info_scroll, True)
        else:
            self.main_view = gtk.VBox()
            self.info_panel = gtk.HBox()
            self.event_box.set_size_request(-1, int(gtk.gdk.screen_height() / 1.60))
            self.main_view.pack_start(self.event_box, False)
            self.main_view.pack_start(info_scroll, True)

        # Create the Moon image widget
        self.image = gtk.Image()
        self.event_box.add(self.image)
        self.event_box.modify_bg(gtk.STATE_NORMAL, self.black_alloc_color)
        self.event_box.connect('size-allocate', self._moon_size_allocate_cb)

        # Create scrolling Moon information panel
        info_scroll.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        info_scroll.set_size_request(-1, -1)

        self.info_panel.set_border_width(10)
        self.info = gtk.Label()
        self.info.set_justify(gtk.JUSTIFY_LEFT)
        self.info.set_alignment(0.0, 0.0)
        self.info_panel.pack_start(self.info, False)
        self.info2 = gtk.Label()
        self.info2.set_justify(gtk.JUSTIFY_LEFT)
        self.info2.set_alignment(0.0, 0.0)
        self.info_panel.pack_start(self.info2, True, True, 10)
        info_scroll.add_with_viewport(self.info_panel)

        # Create Moon data model
        self.data_model = DataModel()

        # Generate first view for text and kick off image update timer
        self.update_text_information_view()
        self.update_moon_image_view()

        # Display everything
        self.info.show()
        self.info_panel.show()
        self.image.show()
        self.event_box.show()
        self.main_view.show()
        self.set_canvas(self.main_view)
        self.show_all()

    def is_landscape_orientation(self):
        """Return True of in landscape, False for portrait orientation.
        """
        if gtk.gdk.screen_width() > gtk.gdk.screen_height():
            return True
        return False

    def read_and_parse_prefs(self, file_path):
        """Parse and set preference data from a given file.
        """
        try:
            read_file = open(file_path, 'r')
            self.activity_state = json.loads(read_file.read())
            if self.activity_state.has_key('hemisphereView'):
                self.hemisphere_view = self.activity_state['hemisphereView']
            if self.activity_state.has_key('showGrid'):
                self.show_grid = self.activity_state['showGrid']
            read_file.close()
        except:
            pass

    def read_file(self, file_path):
        """Read state from datastore.
        """
        self.read_and_parse_prefs(file_path)
        
    def write_file(self, file_path):
        """Write state to journal datastore and to persistent file system.
        """
        self.activity_state['hemisphereView'] = self.hemisphere_view
        self.activity_state['showGrid'] = self.show_grid
        serialised_data = json.dumps(self.activity_state)
        
        to_journal = file(file_path, 'w')
        try:
            to_journal.write(serialised_data)
        finally:
            to_journal.close()
            
        to_persistent_fs = file(self.get_activity_root() + '/data/defaults', 'w')
        try:
            to_persistent_fs.write(serialised_data)
        finally:
            to_persistent_fs.close()
    
    def toggle_grid_clicked(self, widget):
        """Respond to toolbar button to hide/show grid lines.
        """
        if self.show_grid == True:
            self.show_grid = False
        else:
            self.show_grid = True
        gobject.source_remove(self.update_moon_image_timeout)
        self.update_moon_image_view()

    def toggle_hemisphere_clicked(self, widget):
        """Respond to toolbar button to change viewing hemisphere.
        """
        if self.hemisphere_view == 'north':
            self.hemisphere_view = 'south'
        else:
            self.hemisphere_view = 'north'
        gobject.source_remove(self.update_moon_image_timeout)
        self.update_moon_image_view()

    def update_text_information_view(self):
        """Generate Moon data and update text based information view.
        """
        self.data_model.update_moon_calculations(time.time())
        information_string = _("Today's Moon Information\n\n")[:-2]
        information_string += ":\n%s\n\n" % (time.strftime(LOCALE_DATE_FORMAT))
        information_string += (_("Phase:\n%s\n\n") % (self.data_model.moon_phase_name(self.data_model.phase_of_moon))).replace("\n", " ", 1)
        information_string += _("Julian Date:\n%.2f (astronomical)\n\n") % (self.data_model.julian_date)
        information_string += (_("Age:\n%(days).0f days, %(hours).0f hours, %(minutes).0f minutes\n\n") % {'days':self.data_model.days_old, 'hours':self.data_model.hours_old, 'minutes':self.data_model.minutes_old}).replace("\n", " ", 1)
        information_string += _("Lunation:\n%(phase).2f%% through lunation %(lunation)d\n\n") % {'phase':self.data_model.phase_of_moon * 100, 'lunation':self.data_model.lunation}
        information_string += (_("Surface Visibility:\n%.0f%% (estimated)\n\n")[:-2] % (self.data_model.percent_of_full_moon * 100)).replace("\n", " ", 1)
        self.info.set_markup(information_string)

        information_string = _(u"Selenographic Terminator Longitude:\n%(deg).1f\u00b0%(westOrEast)s (%(riseOrSet)s)\n\n") % {'deg':self.data_model.selenographic_deg, 'westOrEast':self.data_model.west_or_east, 'riseOrSet':self.data_model.rise_or_set}
        information_string += _("Next Full Moon:\n%(date)s in %(days).0f days\n\n") % {'date':time.strftime(LOCALE_DATE_FORMAT, time.localtime(self.data_model.next_full_moon_date)), 'days':self.data_model.days_until_full_moon}
        information_string += _("Next New Moon:\n%(date)s in %(days).0f days\n\n") % {'date':time.strftime(LOCALE_DATE_FORMAT, time.localtime(self.data_model.next_new_moon_date)), 'days':self.data_model.days_until_new_moon}
        information_string += _("Next (%(eclipse_type)s) Lunar eclipse:\n%(date)s in %(days).0f days\n\n") % {'date':time.strftime(LOCALE_DATE_FORMAT, time.localtime(self.data_model.next_lunar_eclipse_date)), 'days':self.data_model.days_until_lunar_eclipse, 'eclipse_type':ECLIPSE_TYPES[self.data_model.next_lunar_eclipse_type]}
        information_string += _("Next (%(eclipse_type)s) Solar eclipse:\n%(date)s in %(days).0f days\n\n")[:-2] % {'date':time.strftime(LOCALE_DATE_FORMAT, time.localtime(self.data_model.next_solar_eclipse_date)), 'days':self.data_model.days_until_solar_eclipse, 'eclipse_type':ECLIPSE_TYPES[self.data_model.next_solar_eclipse_type]}
        self.info2.set_markup(information_string)

        # Calculate time to next minute cusp and set a new timer
        ms_to_next_min_cusp = (60 - time.gmtime()[5]) * 1000
        gobject.timeout_add(ms_to_next_min_cusp, self.update_text_information_view)

        # Stop this timer running
        return False

    def update_moon_image_view(self):
        """Update Moon image view using last cached Moon data.
        """
        self.image_pixmap = gtk.gdk.Pixmap(self.window, IMAGE_SIZE, IMAGE_SIZE)
        self.gc = self.image_pixmap.new_gc(foreground=self.black_alloc_color)
        self.image.set_from_pixmap(self.image_pixmap, None)

        # Erase last Moon rendering
        self.image_pixmap.draw_rectangle(self.gc, True, 0, 0, IMAGE_SIZE, IMAGE_SIZE)
                
        # Create a 1bit shadow mask
        mask_pixmap = gtk.gdk.Pixmap(None, IMAGE_SIZE, IMAGE_SIZE, depth=1)
        kgc = mask_pixmap.new_gc(foreground=self.black_alloc_color)
        wgc = mask_pixmap.new_gc(foreground=self.white_alloc_color)
        mask_pixmap.draw_rectangle(kgc, True, 0, 0, IMAGE_SIZE, IMAGE_SIZE)
        if self.data_model.phase_of_moon <= .25:
            # New Moon to First Quarter
            phase_shadow_adjust = self.data_model.phase_of_moon - abs(math.sin(self.data_model.phase_of_moon * math.pi * 4) / 18.0)
            arc_scale = int(IMAGE_SIZE * (1 - (phase_shadow_adjust * 4)))
            mask_pixmap.draw_rectangle(wgc, True, HALF_SIZE + 1, 0, HALF_SIZE, IMAGE_SIZE - 1)
            mask_pixmap.draw_arc(kgc, True, HALF_SIZE - int(arc_scale / 2), 0, arc_scale, IMAGE_SIZE, 17280, 11520)
        elif self.data_model.phase_of_moon <= .5:
            # First Quarter to Full Moon
            phase_shadow_adjust = self.data_model.phase_of_moon + abs(math.sin(self.data_model.phase_of_moon * math.pi * 4) / 18.0)
            arc_scale = int(IMAGE_SIZE * ((phase_shadow_adjust - .25) * 4))
            mask_pixmap.draw_rectangle(wgc, True, HALF_SIZE, 0, HALF_SIZE, IMAGE_SIZE)
            mask_pixmap.draw_arc(wgc, True, HALF_SIZE - int(arc_scale / 2), 0, arc_scale, IMAGE_SIZE, 5760, 11520)
        elif self.data_model.phase_of_moon <= .75:
            # Full Moon to Last Quarter
            phase_shadow_adjust = self.data_model.phase_of_moon - abs(math.sin(self.data_model.phase_of_moon * math.pi * 4) / 18.0)
            arc_scale = int(IMAGE_SIZE * (1 - ((phase_shadow_adjust - .5) * 4)))
            mask_pixmap.draw_rectangle(wgc, True, 0, 0, HALF_SIZE + 1, IMAGE_SIZE)
            mask_pixmap.draw_arc(wgc, True, HALF_SIZE - int(arc_scale / 2), 0, arc_scale, IMAGE_SIZE, 17280, 11520)
        else:
            # Last Quarter to New Moon
            phase_shadow_adjust = self.data_model.phase_of_moon + abs(math.sin(self.data_model.phase_of_moon * math.pi * 4) / 18.0)
            arc_scale = int(IMAGE_SIZE * ((phase_shadow_adjust - .75) * 4))
            mask_pixmap.draw_rectangle(wgc, True, 0, 0, HALF_SIZE, IMAGE_SIZE)
            mask_pixmap.draw_arc(kgc, True, HALF_SIZE - int(arc_scale / 2), 0, arc_scale, IMAGE_SIZE, 5760, 11520)
        maskgc = self.image_pixmap.new_gc(clip_mask=mask_pixmap)
        
        # Modified image based on public domain photo by John MacCooey
        moon_pixbuf = self.moon_stamp.scale_simple(IMAGE_SIZE, IMAGE_SIZE,
                gtk.gdk.INTERP_BILINEAR)

        # Composite bright Moon image and semi-transparant Moon for shadow detail
        dark_pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, IMAGE_SIZE, IMAGE_SIZE)
        dark_pixbuf.fill(0x00000000)
        if (self.data_model.next_lunar_eclipse_sec == -1 and self.data_model.last_lunar_eclipse_sec > 7200) or (self.data_model.next_lunar_eclipse_sec > 7200 and self.data_model.last_lunar_eclipse_sec == -1) or min(self.data_model.next_lunar_eclipse_sec, self.data_model.last_lunar_eclipse_sec) > 7200:
            # Normal Moon phase render
            moon_pixbuf.composite(dark_pixbuf, 0, 0, IMAGE_SIZE, IMAGE_SIZE, 0, 0, 1, 1, gtk.gdk.INTERP_BILINEAR, 127)
            self.image_pixmap.draw_pixbuf(self.gc, dark_pixbuf, 0, 0, 0, 0)
            self.image_pixmap.draw_pixbuf(maskgc, moon_pixbuf, 0, 0, 0, 0)

        else:
            # Reddening eclipse effect, 2hrs (7200sec) before and after (by masking out green & blue)
            if self.data_model.next_lunar_eclipse_sec == -1:
                eclipse_alpha = self.data_model.last_lunar_eclipse_sec / 7200.0 * 256
            elif self.data_model.last_lunar_eclipse_sec == -1:
                eclipse_alpha = self.data_model.next_lunar_eclipse_sec / 7200.0 * 256
            else:
                eclipse_alpha = min(self.data_model.next_lunar_eclipse_sec, self.data_model.last_lunar_eclipse_sec) / 7200.0 * 256
            moon_pixbuf.composite(dark_pixbuf, 0, 0, IMAGE_SIZE, IMAGE_SIZE,
                                  0, 0, 1, 1, gtk.gdk.INTERP_BILINEAR,
                                  int(196 - eclipse_alpha / 2))
            self.image_pixmap.draw_pixbuf(self.gc, dark_pixbuf, 0, 0, 0, 0)
            del dark_pixbuf
            dark_pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, IMAGE_SIZE, IMAGE_SIZE)
            moon_pixbuf.composite(dark_pixbuf, 0, 0, IMAGE_SIZE, IMAGE_SIZE,
                                  0, 0, 1, 1, gtk.gdk.INTERP_BILINEAR,
                                  int(eclipse_alpha))
            rgc = self.image_pixmap.new_gc(foreground=self.blue_green_mask_alloc_color, function=gtk.gdk.AND)
            self.image_pixmap.draw_rectangle(rgc, True, 0, 0, IMAGE_SIZE, IMAGE_SIZE)
            self.image_pixmap.draw_pixbuf(self.gc, dark_pixbuf, 0, 0, 0, 0)

        if self.hemisphere_view == 'south':
            # Rotate final image for a view from north or south hemisphere
            rot_pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, IMAGE_SIZE, IMAGE_SIZE)
            rot_pixbuf.get_from_drawable(self.image_pixmap, self.image_pixmap.get_colormap(), 0, 0, 0, 0, -1, -1)
            rot_pixbuf = rot_pixbuf.rotate_simple(gtk.gdk.PIXBUF_ROTATE_UPSIDEDOWN)
            self.image_pixmap.draw_pixbuf(self.gc, rot_pixbuf, 0, 0, 0, 0)
            if self.show_grid:
                # Draw grid rotated for south hemi
                self.draw_grid(_("SNWE"))
        elif self.show_grid:
            # Draw grid for north hemi
            self.draw_grid(_("NSEW"))

        self.image.queue_draw()

        # Update the Moon image in another 5min
        self.update_moon_image_timeout = gobject.timeout_add(300000, self.update_moon_image_view)
        
        # Stop this timer running
        return False

    def draw_grid(self, compass_text):
        """Draw Selenographic grid line data.
        """
        rgc = self.image_pixmap.new_gc(foreground=self.red_alloc_color)
        bgc = self.image_pixmap.new_gc(foreground=self.blue_alloc_color)
        wgc = self.image_pixmap.new_gc(foreground=self.white_alloc_color)
        pango_layout = self.image.create_pango_layout("")
        pango_layout.set_text("0°")
        self.image_pixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, HALF_SIZE, 24, 22)            
        self.image_pixmap.draw_layout(wgc, HALF_SIZE + 2, HALF_SIZE, pango_layout)            
        pango_layout.set_text("30°")
        self.image_pixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 0.5), 36, 22)            
        self.image_pixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 1.5), 36, 22)            
        self.image_pixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 0.5), pango_layout)            
        self.image_pixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 1.5), pango_layout)            
        pango_layout.set_text("60°")
        self.image_pixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 0.15), 36, 22)            
        self.image_pixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 1.85), 36, 22)            
        self.image_pixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 0.15), pango_layout)            
        self.image_pixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 1.85), pango_layout)            
        pango_layout.set_text("30°")
        self.image_pixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 0.48) + 2, HALF_SIZE, 36, 22)            
        self.image_pixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 1.52) + 2, HALF_SIZE, 36, 22)            
        self.image_pixmap.draw_layout(wgc, int(HALF_SIZE * 0.48) + 2, HALF_SIZE, pango_layout)            
        self.image_pixmap.draw_layout(wgc, int(HALF_SIZE * 1.52) + 2, HALF_SIZE, pango_layout)            
        pango_layout.set_text("60°")
        self.image_pixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 0.15) + 2, HALF_SIZE, 36, 22)            
        self.image_pixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 1.85) + 2, HALF_SIZE, 36, 22)            
        self.image_pixmap.draw_layout(wgc, int(HALF_SIZE * 0.15) + 2, HALF_SIZE, pango_layout)            
        self.image_pixmap.draw_layout(wgc, int(HALF_SIZE * 1.85) + 2, HALF_SIZE, pango_layout)            
        for i in (-1, 0, 1):
            self.image_pixmap.draw_line(rgc, HALF_SIZE + i, 0, HALF_SIZE + i, IMAGE_SIZE)
            self.image_pixmap.draw_arc(rgc, False, int(HALF_SIZE * 0.15) + i, 0, IMAGE_SIZE - int(IMAGE_SIZE * 0.15), IMAGE_SIZE, 0, 360*64)
            self.image_pixmap.draw_arc(rgc, False, int(HALF_SIZE * 0.48) + i, 0, IMAGE_SIZE - int(IMAGE_SIZE * 0.48) , IMAGE_SIZE, 0, 360*64)
        for i in (-1, 0, 1):
            self.image_pixmap.draw_line(bgc, 0, HALF_SIZE + i, IMAGE_SIZE, HALF_SIZE + i)
            self.image_pixmap.draw_line(bgc, int(HALF_SIZE * 0.15), int(HALF_SIZE * 0.5) + i, IMAGE_SIZE - int(HALF_SIZE * 0.15), int(HALF_SIZE * 0.5) + i)
            self.image_pixmap.draw_line(bgc, int(HALF_SIZE * 0.15), int(HALF_SIZE * 1.5) + i, IMAGE_SIZE - int(HALF_SIZE * 0.15), int(HALF_SIZE * 1.5) + i)
            self.image_pixmap.draw_line(bgc, int(HALF_SIZE * 0.5), int(HALF_SIZE * 0.15) + i, IMAGE_SIZE - int(HALF_SIZE * 0.5), int(HALF_SIZE * 0.15) + i)
            self.image_pixmap.draw_line(bgc, int(HALF_SIZE * 0.5), int(HALF_SIZE * 1.85) + i, IMAGE_SIZE - int(HALF_SIZE * 0.5), int(HALF_SIZE * 1.85) + i)

        # Key text
        pango_layout.set_text(_("Latitude"))
        self.image_pixmap.draw_layout(bgc, 15, IMAGE_SIZE - 48 - 15, pango_layout)
        pango_layout.set_text(_("Longitude"))
        self.image_pixmap.draw_layout(rgc, 15, IMAGE_SIZE - 24 - 15, pango_layout)

        # Compass
        # TODO: fix string index to support multi-byte texts
        for i in (-1, 0, 1):
            self.image_pixmap.draw_line(rgc, 22 + 15, 48 + 15 + i, 68 + 15, 48 + 15 + i)
        for i in (-1, 0, 1):
            self.image_pixmap.draw_line(bgc, 45 + 15 + i, 24 + 15, 45 + 15 + i, 68 + 15)
        pango_layout.set_text(compass_text[0])
        self.image_pixmap.draw_layout(bgc, 38 + 15, 15, pango_layout)
        pango_layout.set_text(compass_text[1])
        self.image_pixmap.draw_layout(bgc, 38 + 15, 72 + 15, pango_layout)
        pango_layout.set_text(compass_text[2])
        self.image_pixmap.draw_layout(rgc, 72 + 15, 36 + 15, pango_layout)
        pango_layout.set_text(compass_text[3])
        self.image_pixmap.draw_layout(rgc, 15, 36 + 15, pango_layout)

    def _moon_size_allocate_cb(self, widget, allocation):
        global IMAGE_SIZE, HALF_SIZE
        size = min(allocation.width, allocation.height) - 30

        if size != IMAGE_SIZE and size != self.image_size_cache:
            self.image_size_cache = size
            IMAGE_SIZE = size
            HALF_SIZE = IMAGE_SIZE / 2
            self.update_moon_image_view()

    def save_image(self, widget):
        """
        Save the curren phase to image and show alert
        """

        w, h = self.get_size()
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8,
                    int(w / 1.70), h - 55)

        shot = pixbuf.get_from_drawable(self.window, self.get_colormap(),
                    w - int(w / 1.70), 55, 0, 0, int(w / 1.70), h - 55)

        path = os.path.join(activity.get_activity_root(), "instance",
            "shot.png")

        shot.save(path, "png")
        journal_entry = datastore.create()
        journal_entry.metadata['title'] = "%s %s" % \
            (self.metadata['title'], _("Image"))
        journal_entry.metadata['icon-color'] = profile.get_color().to_string()
        journal_entry.metadata['mime_type'] = "image/png"
        journal_entry.set_file_path(path)
        datastore.write(journal_entry)
        journal_entry.destroy()

        # Alert
        HAS_ALERT = False
        try:
            from sugar.graphics.alert import NotifyAlert
            HAS_ALERT = True
        except:
            pass

        if HAS_ALERT:
            alert = NotifyAlert(5)
            alert.props.title =_('Image saved')
            alert.props.msg = _('An image of the current phase of the moon has been saved to the Journal')
            alert.connect('response', lambda x, y: self.remove_alert(x))
            self.add_alert(alert)


class DataModel():
    """Moon phase data model and various utility methods.
    """

    def __init__(self):
        """Init hard coded, tupules for New, First Quarter, Full Last
        Quarter Moon UTC data.

        2018 to 2028 data from
        http://sunearth.gsfc.nasa.gov/eclipse/phase/phasecat.html (now
        only found on web.archive.org) algorithms used in predicting
        the phases of the Moon and eclipses are based on Jean Meeus'
        Astronomical Algorithms (Willmann-Bell, Inc., 1998). All
        calculations are by Fred Espenak, and he assumes full
        responsibility for their accuracy. Permission is freely
        granted to reproduce this data when accompanied by an
        acknowledgment.

        Data is all UTC and in YYYY-MM-DD HH:MM format, with New and
        Full Moon arrays with an extra end character for eclipse types
        T=Total (Solar), A=Annular (Solar), H=Hybrid (Solar
        Annular/Total), P=Partial (Solar), t=Total (Lunar Umbral),
        p=Partial (Lunar Umbral), n=Penumbral (Lunar), _=none.
        """

        self.date_format = "%Y-%m-%d %H:%M"
        self.new_moon_array = (
            "2018-01-17 02:17_", "2018-02-15 21:05P", "2018-03-17 13:12_",
            "2018-04-16 01:57_", "2018-05-15 11:48_", "2018-06-13 19:43_",
            "2018-07-13 02:48P", "2018-08-11 09:58P", "2018-09-09 18:01_",
            "2018-10-09 03:47_", "2018-11-07 16:02_", "2018-12-07 07:20_",
            "2019-01-06 01:28P", "2019-02-04 21:04_", "2019-03-06 16:04_",
            "2019-04-05 08:50_", "2019-05-04 22:45_", "2019-06-03 10:02_",
            "2019-07-02 19:16T", "2019-08-01 03:12_", "2019-08-30 10:37_",
            "2019-09-28 18:26_", "2019-10-28 03:38_", "2019-11-26 15:06_",
            "2019-12-26 05:13A", "2020-01-24 21:42_", "2020-02-23 15:32_",
            "2020-03-24 09:28_", "2020-04-23 02:26_", "2020-05-22 17:39_",
            "2020-06-21 06:41A", "2020-07-20 17:33_", "2020-08-19 02:41_",
            "2020-09-17 11:00_", "2020-10-16 19:31_", "2020-11-15 05:07_",
            "2020-12-14 16:17T", "2021-01-13 05:00_", "2021-02-11 19:06_",
            "2021-03-13 10:21_", "2021-04-12 02:31_", "2021-05-11 19:00_",
            "2021-06-10 10:53A", "2021-07-10 01:17_", "2021-08-08 13:50_",
            "2021-09-07 00:52_", "2021-10-06 11:05_", "2021-11-04 21:15_",
            "2021-12-04 07:43T", "2022-01-02 18:33_", "2022-02-01 05:46_",
            "2022-03-02 17:35_", "2022-04-01 06:24_", "2022-04-30 20:28P",
            "2022-05-30 11:30_", "2022-06-29 02:52_", "2022-07-28 17:55_",
            "2022-08-27 08:17_", "2022-09-25 21:54_", "2022-10-25 10:49P",
            "2022-11-23 22:57_", "2022-12-23 10:17_", "2023-01-21 20:53_",
            "2023-02-20 07:06_", "2023-03-21 17:23_", "2023-04-20 04:12H",
            "2023-05-19 15:53_", "2023-06-18 04:37_", "2023-07-17 18:32_",
            "2023-08-16 09:38_", "2023-09-15 01:40_", "2023-10-14 17:55A",
            "2023-11-13 09:27_", "2023-12-12 23:32_", "2024-01-11 11:57_",
            "2024-02-09 22:59_", "2024-03-10 09:00_", "2024-04-08 18:21T",
            "2024-05-08 03:22_", "2024-06-06 12:38_", "2024-07-05 22:57_",
            "2024-08-04 11:13_", "2024-09-03 01:55_", "2024-10-02 18:49A",
            "2024-11-01 12:47_", "2024-12-01 06:21_", "2024-12-30 22:27_")
        self.full_moon_array = (
            "2018-01-02 02:24_", "2018-01-31 13:27t", "2018-03-02 00:51_",
            "2018-03-31 12:37_", "2018-04-30 00:58_", "2018-05-29 14:20_",
            "2018-06-28 04:53_", "2018-07-27 20:20t", "2018-08-26 11:56_",
            "2018-09-25 02:53_", "2018-10-24 16:45_", "2018-11-23 05:39_",
            "2018-12-22 17:49_", "2019-01-21 05:16t", "2019-02-19 15:53_",
            "2019-03-21 01:43_", "2019-04-19 11:12_", "2019-05-18 21:11_",
            "2019-06-17 08:31_", "2019-07-16 21:38p", "2019-08-15 12:29_",
            "2019-09-14 04:33_", "2019-10-13 21:08_", "2019-11-12 13:34_",
            "2019-12-12 05:12_", "2020-01-10 19:21n", "2020-02-09 07:33_",
            "2020-03-09 17:48_", "2020-04-08 02:35_", "2020-05-07 10:45_",
            "2020-06-05 19:12n", "2020-07-05 04:44n", "2020-08-03 15:59_",
            "2020-09-02 05:22_", "2020-10-01 21:05_", "2020-10-31 14:49_",
            "2020-11-30 09:30n", "2020-12-30 03:28_", "2021-01-28 19:16_",
            "2021-02-27 08:17_", "2021-03-28 18:48_", "2021-04-27 03:31_",
            "2021-05-26 11:14t", "2021-06-24 18:40_", "2021-07-24 02:37_",
            "2021-08-22 12:02_", "2021-09-20 23:55_", "2021-10-20 14:57_",
            "2021-11-19 08:58p", "2021-12-19 04:36_", "2022-01-17 23:49_",
            "2022-02-16 16:57_", "2022-03-18 07:17_", "2022-04-16 18:55_",
            "2022-05-16 04:14t", "2022-06-14 11:52_", "2022-07-13 18:37_",
            "2022-08-12 01:36_", "2022-09-10 09:59_", "2022-10-09 20:55_",
            "2022-11-08 11:02t", "2022-12-08 04:08_", "2023-01-06 23:08_",
            "2023-02-05 18:29_", "2023-03-07 12:40_", "2023-04-06 04:35_",
            "2023-05-05 17:34n", "2023-06-04 03:42_", "2023-07-03 11:39_",
            "2023-08-01 18:31_", "2023-08-31 01:35_", "2023-09-29 09:57_",
            "2023-10-28 20:24p", "2023-11-27 09:16_", "2023-12-27 00:33_",
            "2024-01-25 17:54_", "2024-02-24 12:30_", "2024-03-25 07:00n",
            "2024-04-23 23:49_", "2024-05-23 13:53_", "2024-06-22 01:08_",
            "2024-07-21 10:17_", "2024-08-19 18:26_", "2024-09-18 02:34p",
            "2024-10-17 11:26_", "2024-11-15 21:29_", "2024-12-15 09:02_")
        self.first_quarter_array = (
            "2018-01-24 22:20", "2018-02-23 08:09", "2018-03-24 15:35",
            "2018-04-22 21:46", "2018-05-22 03:49", "2018-06-20 10:51",
            "2018-07-19 19:52", "2018-08-18 07:49", "2018-09-16 23:15",
            "2018-10-16 18:02", "2018-11-15 14:54", "2018-12-15 11:49",
            "2019-01-14 06:45", "2019-02-12 22:26", "2019-03-14 10:27",
            "2019-04-12 19:06", "2019-05-12 01:12", "2019-06-10 05:59",
            "2019-07-09 10:55", "2019-08-07 17:31", "2019-09-06 03:10",
            "2019-10-05 16:47", "2019-11-04 10:23", "2019-12-04 06:58",
            "2020-01-03 04:45", "2020-02-02 01:42", "2020-03-02 19:57",
            "2020-04-01 10:21", "2020-04-30 20:38", "2020-05-30 03:30",
            "2020-06-28 08:16", "2020-07-27 12:32", "2020-08-25 17:58",
            "2020-09-24 01:55", "2020-10-23 13:23", "2020-11-22 04:45",
            "2020-12-21 23:41", "2021-01-20 21:02", "2021-02-19 18:47",
            "2021-03-21 14:40", "2021-04-20 06:59", "2021-05-19 19:13",
            "2021-06-18 03:54", "2021-07-17 10:11", "2021-08-15 15:20",
            "2021-09-13 20:39", "2021-10-13 03:25", "2021-11-11 12:46",
            "2021-12-11 01:36", "2022-01-09 18:11", "2022-02-08 13:50",
            "2022-03-10 10:45", "2022-04-09 06:47", "2022-05-09 00:21",
            "2022-06-07 14:48", "2022-07-07 02:14", "2022-08-05 11:06",
            "2022-09-03 18:08", "2022-10-03 00:14", "2022-11-01 06:37",
            "2022-11-30 14:36", "2022-12-30 01:21", "2023-01-28 15:19",
            "2023-02-27 08:06", "2023-03-29 02:32", "2023-04-27 21:20",
            "2023-05-27 15:22", "2023-06-26 07:50", "2023-07-25 22:07",
            "2023-08-24 09:57", "2023-09-22 19:32", "2023-10-22 03:29",
            "2023-11-20 10:50", "2023-12-19 18:39", "2024-01-18 03:53",
            "2024-02-16 15:01", "2024-03-17 04:11", "2024-04-15 19:13",
            "2024-05-15 11:48", "2024-06-14 05:18", "2024-07-13 22:49",
            "2024-08-12 15:19", "2024-09-11 06:06", "2024-10-10 18:55",
            "2024-11-09 05:56", "2024-12-08 15:27")
        self.last_quarter_array = (
            "2018-01-08 22:25", "2018-02-07 15:54", "2018-03-09 11:20",
            "2018-04-08 07:18", "2018-05-08 02:09", "2018-06-06 18:32",
            "2018-07-06 07:51", "2018-08-04 18:18", "2018-09-03 02:37",
            "2018-10-02 09:45", "2018-10-31 16:40", "2018-11-30 00:19",
            "2018-12-29 09:34", "2019-01-27 21:10", "2019-02-26 11:28",
            "2019-03-28 04:10", "2019-04-26 22:18", "2019-05-26 16:33",
            "2019-06-25 09:46", "2019-07-25 01:18", "2019-08-23 14:56",
            "2019-09-22 02:41", "2019-10-21 12:39", "2019-11-19 21:11",
            "2019-12-19 04:57", "2020-01-17 12:58", "2020-02-15 22:17",
            "2020-03-16 09:34", "2020-04-14 22:56", "2020-05-14 14:03",
            "2020-06-13 06:24", "2020-07-12 23:29", "2020-08-11 16:45",
            "2020-09-10 09:26", "2020-10-10 00:39", "2020-11-08 13:46",
            "2020-12-08 00:37", "2021-01-06 09:37", "2021-02-04 17:37",
            "2021-03-06 01:30", "2021-04-04 10:02", "2021-05-03 19:50",
            "2021-06-02 07:24", "2021-07-01 21:11", "2021-07-31 13:16",
            "2021-08-30 07:13", "2021-09-29 01:57", "2021-10-28 20:05",
            "2021-11-27 12:28", "2021-12-27 02:24", "2022-01-25 13:41",
            "2022-02-23 22:32", "2022-03-25 05:37", "2022-04-23 11:56",
            "2022-05-22 18:43", "2022-06-21 03:11", "2022-07-20 14:18",
            "2022-08-19 04:36", "2022-09-17 21:52", "2022-10-17 17:15",
            "2022-11-16 13:27", "2022-12-16 08:56", "2023-01-15 02:10",
            "2023-02-13 16:01", "2023-03-15 02:08", "2023-04-13 09:11",
            "2023-05-12 14:28", "2023-06-10 19:31", "2023-07-10 01:48",
            "2023-08-08 10:28", "2023-09-06 22:21", "2023-10-06 13:48",
            "2023-11-05 08:37", "2023-12-05 05:49", "2024-01-04 03:30",
            "2024-02-02 23:18", "2024-03-03 15:24", "2024-04-02 03:15",
            "2024-05-01 11:27", "2024-05-30 17:13", "2024-06-28 21:53",
            "2024-07-28 02:51", "2024-08-26 09:26", "2024-09-24 18:50",
            "2024-10-24 08:03", "2024-11-23 01:28", "2024-12-22 22:18")

    def update_moon_calculations(self, the_date):
        """Generate all Moon data ready for display.
        """
        SECONDS_PER_DAY = 86400.0
        last_new_moon_sec = self.last_new_moon_sec_at_time(the_date)
        next_new_moon_sec = self.next_new_moon_sec_at_time(the_date)
        last_full_moon_sec = self.last_full_moon_sec_at_time(the_date)
        next_full_moon_sec = self.next_full_moon_sec_at_time(the_date)
        last_quarter_moon_sec = self.last_quarter_moon_sec_at_time(the_date)
        next_quarter_moon_sec = self.next_quarter_moon_sec_at_time(the_date)

        # Calculate phase percent of Moon based on nearest two data values
        if next_full_moon_sec <= next_new_moon_sec:
            if next_quarter_moon_sec <= next_full_moon_sec:
                self.phase_of_moon = (last_new_moon_sec / (last_new_moon_sec + next_quarter_moon_sec)) * 0.25
            else:
                self.phase_of_moon = (last_quarter_moon_sec / (last_quarter_moon_sec + next_full_moon_sec)) * 0.25 + 0.25
        else:
            if next_quarter_moon_sec <= next_new_moon_sec:
                self.phase_of_moon = (last_full_moon_sec / (last_full_moon_sec + next_quarter_moon_sec)) * 0.25 + 0.5
            else:
                self.phase_of_moon = (last_quarter_moon_sec / (last_quarter_moon_sec + next_new_moon_sec)) * 0.25 + 0.75

        # Generate interesting human readable values
        self.percent_of_full_moon = (math.cos(((self.phase_of_moon + .5) / .5 * math.pi)) + 1) * .5
        self.julian_date = 2452135 + ((the_date - 997700400.0) / SECONDS_PER_DAY)
        self.lunation = self.lunation_at_time(the_date)
        day_with_fraction = last_new_moon_sec / SECONDS_PER_DAY
        self.days_old = math.floor(day_with_fraction)
        self.hours_old = math.floor((day_with_fraction - self.days_old) * 24)
        self.minutes_old = math.floor((((day_with_fraction - self.days_old) * 24) - self.hours_old) * 60)
        self.days_until_new_moon = next_new_moon_sec / SECONDS_PER_DAY
        self.next_new_moon_date = the_date + next_new_moon_sec - self.correct_for_tz_and_dst(the_date + next_new_moon_sec)
        self.days_until_full_moon = next_full_moon_sec / SECONDS_PER_DAY
        self.next_full_moon_date = the_date + next_full_moon_sec - self.correct_for_tz_and_dst(the_date + next_full_moon_sec)
        
        # Eclipse information
        self.next_lunar_eclipse_sec, self.next_lunar_eclipse_type = self.next_lunar_eclipse_sec_at_time(the_date)
        self.next_solar_eclipse_sec, self.next_solar_eclipse_type = self.next_solar_eclipse_sec_at_time(the_date)
        self.last_lunar_eclipse_sec, self.last_lunar_eclipse_type = self.last_lunar_eclipse_sec_at_time(the_date)
        self.days_until_lunar_eclipse = self.next_lunar_eclipse_sec / SECONDS_PER_DAY
        self.next_lunar_eclipse_date = the_date + self.next_lunar_eclipse_sec - self.correct_for_tz_and_dst(the_date + self.next_lunar_eclipse_sec)
        self.days_until_solar_eclipse = self.next_solar_eclipse_sec / SECONDS_PER_DAY
        self.next_solar_eclipse_date = the_date + self.next_solar_eclipse_sec - self.correct_for_tz_and_dst(the_date + self.next_solar_eclipse_sec)

        # Selenographic terminator longitude
        selenographic_tmp = 270 + (self.phase_of_moon * 360)
        if selenographic_tmp >= 360:
            selenographic_tmp -= 360
        if selenographic_tmp >= 270:
            selenographic_tmp -= 360
        elif selenographic_tmp >= 180:
            selenographic_tmp -= 180
        elif selenographic_tmp >= 90:
            selenographic_tmp -= 180
        selenographic_tmp = -selenographic_tmp
        if selenographic_tmp < 0:
            self.west_or_east = _("west")
        else:
            self.west_or_east = _("east")
        self.selenographic_deg = abs(selenographic_tmp)
        if self.phase_of_moon >= .5:
            self.rise_or_set = _("Sunset")
        else:
            self.rise_or_set = _("Sunrise")
            
    def correct_for_tz_and_dst(self, date_sec_of_event):
        """Time-zone and/or daylight-saving correction (internal data is UTC).
        """
        if time.daylight == 0 or time.localtime(date_sec_of_event)[8] == 0:
            # Time-zone correction
            return time.timezone
        else:
            # Time-zone & daylight saving correction
            return time.altzone

    def moon_phase_name(self, phase_of_moon):
        """Return the moon image name for a given phase value.
        """
        if phase_of_moon >= 0 and phase_of_moon < 0.025:
            return _("New Moon")
        elif phase_of_moon >= 0.025 and phase_of_moon < 0.225:
            return _("Waxing Crescent")
        elif phase_of_moon >= 0.225 and phase_of_moon < 0.275:
            return _("First Quarter")
        elif phase_of_moon >= 0.275 and phase_of_moon < 0.475:
            return _("Waxing Gibbous")
        elif phase_of_moon >= 0.475 and phase_of_moon < 0.525:
            return _("Full Moon")
        elif phase_of_moon >= 0.525 and phase_of_moon < 0.735:
            return _("Waning Gibbous")
        elif phase_of_moon >= 0.735 and phase_of_moon < 0.775:
            return _("Last Quarter")
        elif phase_of_moon >= 0.775 and phase_of_moon < 0.975:
            return _("Waning Crescent")
        else:
            return _("New Moon")

    def next_full_moon_sec_at_time(self, now):
        """Return seconds to the next Full Moon.
        """
        for date_string in self.full_moon_array:
            next = time.mktime(time.strptime(date_string[:-1], self.date_format))
            if next >= now:
                break
        return next - now

    def next_new_moon_sec_at_time(self, now):
        """Return seconds to the next New Moon.
        """
        for date_string in self.new_moon_array:
            next = time.mktime(time.strptime(date_string[:-1], self.date_format))
            if next >= now:
                break
        return next - now

    def next_quarter_moon_sec_at_time(self, now):
        """Return seconds to the next Quater Moon phase (could be First or Last).
        """
        for date_string in self.first_quarter_array:
            next1 = time.mktime(time.strptime(date_string, self.date_format))
            if next1 >= now:
                break
        for date_string in self.last_quarter_array:
            next2 = time.mktime(time.strptime(date_string, self.date_format))
            if next2 >= now:
                break
        next = min(next1, next2)
        return next - now

    def last_full_moon_sec_at_time(self, now):
        """Return (positive) seconds since the last Full Moon.
        """
        for date_string in self.full_moon_array:
            then = time.mktime(time.strptime(date_string[:-1], self.date_format))
            if then >= now:
                break
            last = then
        return now - last

    def last_new_moon_sec_at_time(self, now):
        """Return (positive) seconds since the last New Moon.
        """
        for date_string in self.new_moon_array:
            then = time.mktime(time.strptime(date_string[:-1], self.date_format))
            if then >= now:
                break
            last = then
        return now - last

    def last_quarter_moon_sec_at_time(self, now):
        """Return (positive) seconds to the last Quater Moon phase (could be First or Last).
        """
        for date_string in self.first_quarter_array:
            then = time.mktime(time.strptime(date_string, self.date_format))
            if then >= now:
                break
            last1 = then
        for date_string in self.last_quarter_array:
            then = time.mktime(time.strptime(date_string, self.date_format))
            if then >= now:
                break
            last2 = then
        last = max(last1, last2)
        return now - last

    def lunation_at_time(self, now):
        """Return lunation number, 0 started on Dec 18, 1922, current data set starts as 2008
        """
        lunation = 1051
        for date_string in self.new_moon_array:
            next = time.mktime(time.strptime(date_string[:-1], self.date_format))
            if next >= now:
                break
            lunation += 1
        return lunation

    def next_lunar_eclipse_sec_at_time(self, now):
        """Return (positive) seconds to the next Lunar eclipe or -1.
        """
        for date_string in self.full_moon_array:
            if date_string[-1:] != "_":
                next = time.mktime(time.strptime(date_string[:-1], self.date_format))
                if next >= now:
                    return next - now, date_string[-1:]
        return -1

    def last_lunar_eclipse_sec_at_time(self, now):
        """Return (positive) seconds to the last Lunar eclipe or -1.
        """
        last = -1
        for date_string in self.full_moon_array:
            if date_string[-1:] != "_":
                eclipse_type = date_string[-1:]
                then = time.mktime(time.strptime(date_string[:-1], self.date_format))
                if then >= now:
                    break
                last = then
        if last == -1:
            return -1
        else:
            return now - last, type

    def next_solar_eclipse_sec_at_time(self, now):
        """Return (positive) seconds to the next Solar eclipe or -1.
        """
        for date_string in self.new_moon_array:
            if date_string[-1:] != "_":
                next = time.mktime(time.strptime(date_string[:-1], self.date_format))
                if next >= now:
                    return next - now, date_string[-1:]
        return -1
