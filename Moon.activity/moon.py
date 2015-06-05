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

try:
    # >= 0.86 toolbars
    from sugar.graphics.toolbarbox import ToolbarButton, ToolbarBox
    from sugar.activity.widgets import ActivityToolbarButton
    from sugar.activity.widgets import StopButton
except ImportError:
    # <= 0.84 toolbars
    pass

IMAGE_SIZE = 726
HALF_SIZE = IMAGE_SIZE / 2

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
        if handle.object_id == None:
            print "Launched from home."
        else:
            print "Journal resume."
        self.hemisphere_view = 'north'
        self.show_grid = False
        self.activity_state = {}
        self.activity_state['hemisphereView'] = self.hemisphere_view
        self.activity_state['showGrid'] = self.show_grid
        self.read_and_parse_prefs(os.environ['SUGAR_ACTIVITY_ROOT'] + '/data/defaults')
                
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
            # Use old <= 0.84 toolbar design
            toolbox = activity.ActivityToolbox(self)
            view_tool_bar = gtk.Toolbar()
            self.toggle_grid_button = ToggleToolButton('grid-icon')
            self.toggle_grid_button.set_tooltip(_("Toggle Grid View"))
            self.toggle_grid_button.set_active(self.show_grid)
            self.toggle_grid_handler_id = self.toggle_grid_button.connect('clicked', self.toggle_grid_clicked)
            view_tool_bar.insert(self.toggle_grid_button, -1)
            self.toggle_grid_button.show()
            self.toggle_hemisphere_button = ToggleToolButton('hemi-icon')
            self.toggle_hemisphere_button.set_tooltip(_("Toggle Hemisphere View"))
            self.toggle_hemisphere_button.set_active(self.hemisphere_view == 'south')
            self.toggle_hemisphere_handler_id = self.toggle_hemisphere_button.connect('clicked', self.toggle_hemisphere_clicked)
            view_tool_bar.insert(self.toggle_hemisphere_button, -1)
            self.toggle_hemisphere_button.show()

            self.image_button = ToolButton('save-image')
            self.image_button.set_tooltip(_("Save As Image"))
            self.image_button.connect('clicked', self.save_image)
            toolbar_box.toolbar.insert(self.image_button, -1)
            self.image_button.show()

            view_tool_bar.show()
            toolbox.add_toolbar(_('View'), view_tool_bar)
            self.set_toolbox(toolbox)
            toolbox.show()
            activity_toolbar = toolbox.get_activity_toolbar()
            activity_toolbar.share.props.visible = False

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
            
        to_persistent_fs = file(os.environ['SUGAR_ACTIVITY_ROOT'] + '/data/defaults', 'w')
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
        information_string += _("Next Lunar eclipse:\n%(date)s in %(days).0f days\n\n") % {'date':time.strftime(LOCALE_DATE_FORMAT, time.localtime(self.data_model.next_lunar_eclipse_date)), 'days':self.data_model.days_until_lunar_eclipse}
        information_string += _("Next Solar eclipse:\n%(date)s in %(days).0f days\n\n")[:-2] % {'date':time.strftime(LOCALE_DATE_FORMAT, time.localtime(self.data_model.next_solar_eclipse_date)), 'days':self.data_model.days_until_solar_eclipse}
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
        """Init hard coded, tupules for New, First Quarter, Full Last Quarter Moon UTC data.
        
        2008 to 2018 data from http://sunearth.gsfc.nasa.gov/eclipse/phase/phasecat.html
        algorithms used in predicting the phases of the Moon and eclipses are based
        on Jean Meeus' Astronomical Algorithms (Willmann-Bell, Inc., 1998). All
        calculations are by Fred Espenak, and he assumes full responsibility for
        their accuracy. Permission is freely granted to reproduce this data when
        accompanied by an acknowledgment.
        
        Data is all UTC and in YYYY-MM-DD HH:MM format, with New and Full Moon
        arrays with an extra end character for eclipse types T=Total (Solar),
        A=Annular (Solar), H=Hybrid (Solar Annular/Total), P=Partial (Solar),
        t=Total (Lunar Umbral), p=Partial (Lunar Umbral), n=Penumbral (Lunar),
        _=none.
        """
        
        self.date_format = "%Y-%m-%d %H:%M"
        self.new_moon_array = ("2008-01-08 11:37_", "2008-02-07 03:44A", "2008-03-07 17:14_", "2008-04-06 03:55_", "2008-05-05 12:18_", "2008-06-03 19:23_", "2008-07-03 02:19_", "2008-08-01 10:13T", "2008-08-30 19:58_", "2008-09-29 08:12_", "2008-10-28 23:14_", "2008-11-27 16:55_", "2008-12-27 12:23_", "2009-01-26 07:55A", "2009-02-25 01:35_", "2009-03-26 16:06_", "2009-04-25 03:23_", "2009-05-24 12:11_", "2009-06-22 19:35_", "2009-07-22 02:35T", "2009-08-20 10:01_", "2009-09-18 18:44_", "2009-10-18 05:33_", "2009-11-16 19:14_", "2009-12-16 12:02_", "2010-01-15 07:11A", "2010-02-14 02:51_", "2010-03-15 21:01_", "2010-04-14 12:29_", "2010-05-14 01:04_", "2010-06-12 11:15_", "2010-07-11 19:40T", "2010-08-10 03:08_", "2010-09-08 10:30_", "2010-10-07 18:44_", "2010-11-06 04:52_", "2010-12-05 17:36_", "2011-01-04 09:03P", "2011-02-03 02:31_", "2011-03-04 20:46_", "2011-04-03 14:32_", "2011-05-03 06:51_", "2011-06-01 21:03P", "2011-07-01 08:54P", "2011-07-30 18:40_", "2011-08-29 03:04_", "2011-09-27 11:09_", "2011-10-26 19:56_", "2011-11-25 06:10P", "2011-12-24 18:06_", "2012-01-23 07:39_", "2012-02-21 22:35_", "2012-03-22 14:37_", "2012-04-21 07:18_", "2012-05-20 23:47A", "2012-06-19 15:02_", "2012-07-19 04:24_", "2012-08-17 15:54_", "2012-09-16 02:11_", "2012-10-15 12:02_", "2012-11-13 22:08T", "2012-12-13 08:42_", "2013-01-11 19:44_", "2013-02-10 07:20_", "2013-03-11 19:51_", "2013-04-10 09:35_", "2013-05-10 00:29A", "2013-06-08 15:56_", "2013-07-08 07:14_", "2013-08-06 21:51_", "2013-09-05 11:36_", "2013-10-05 00:35_", "2013-11-03 12:50H", "2013-12-03 00:22_", "2014-01-01 11:14_", "2014-01-30 21:39_", "2014-03-01 08:00_", "2014-03-30 18:45_", "2014-04-29 06:14A", "2014-05-28 18:40_", "2014-06-27 08:09_", "2014-07-26 22:42_", "2014-08-25 14:13_", "2014-09-24 06:14_", "2014-10-23 21:57P", "2014-11-22 12:32_", "2014-12-22 01:36_", "2015-01-20 13:14_", "2015-02-18 23:47_", "2015-03-20 09:36T", "2015-04-18 18:57_", "2015-05-18 04:13_", "2015-06-16 14:05_", "2015-07-16 01:24_", "2015-08-14 14:54_", "2015-09-13 06:41P", "2015-10-13 00:06_", "2015-11-11 17:47_", "2015-12-11 10:29_", "2016-01-10 01:30_", "2016-02-08 14:39_", "2016-03-09 01:54T", "2016-04-07 11:24_", "2016-05-06 19:30_", "2016-06-05 03:00_", "2016-07-04 11:01_", "2016-08-02 20:45_", "2016-09-01 09:03A", "2016-10-01 00:12_", "2016-10-30 17:38_", "2016-11-29 12:18_", "2016-12-29 06:53_", "2017-01-28 00:07_", "2017-02-26 14:58A", "2017-03-28 02:57_", "2017-04-26 12:16_", "2017-05-25 19:44_", "2017-06-24 02:31_", "2017-07-23 09:46_", "2017-08-21 18:30T", "2017-09-20 05:30_", "2017-10-19 19:12_", "2017-11-18 11:42_", "2017-12-18 06:31_", "2018-01-17 02:17_", "2018-02-15 21:05P", "2018-03-17 13:12_", "2018-04-16 01:57_", "2018-05-15 11:48_", "2018-06-13 19:43_", "2018-07-13 02:48P", "2018-08-11 09:58P", "2018-09-09 18:01_", "2018-10-09 03:47_", "2018-11-07 16:02_", "2018-12-07 07:20_")
        self.full_moon_array = ("2008-01-22 13:35_", "2008-02-21 03:31t", "2008-03-21 18:40_", "2008-04-20 10:25_", "2008-05-20 02:11_", "2008-06-18 17:30_", "2008-07-18 07:59_", "2008-08-16 21:16p", "2008-09-15 09:13_", "2008-10-14 20:03_", "2008-11-13 06:17_", "2008-12-12 16:37_", "2009-01-11 03:27_", "2009-02-09 14:49n", "2009-03-11 02:38_", "2009-04-09 14:56_", "2009-05-09 04:01_", "2009-06-07 18:12_", "2009-07-07 09:21n", "2009-08-06 00:55n", "2009-09-04 16:03_", "2009-10-04 06:10_", "2009-11-02 19:14_", "2009-12-02 07:30_", "2009-12-31 19:13p", "2010-01-30 06:18_", "2010-02-28 16:38_", "2010-03-30 02:25_", "2010-04-28 12:18_", "2010-05-27 23:07_", "2010-06-26 11:30p", "2010-07-26 01:37_", "2010-08-24 17:05_", "2010-09-23 09:17_", "2010-10-23 01:36_", "2010-11-21 17:27_", "2010-12-21 08:13t", "2011-01-19 21:21_", "2011-02-18 08:36_", "2011-03-19 18:10_", "2011-04-18 02:44_", "2011-05-17 11:09_", "2011-06-15 20:13t", "2011-07-15 06:40_", "2011-08-13 18:58_", "2011-09-12 09:27_", "2011-10-12 02:06_", "2011-11-10 20:16_", "2011-12-10 14:36t", "2012-01-09 07:30_", "2012-02-07 21:54_", "2012-03-08 09:40_", "2012-04-06 19:19_", "2012-05-06 03:35_", "2012-06-04 11:12p", "2012-07-03 18:52_", "2012-08-02 03:27_", "2012-08-31 13:58_", "2012-09-30 03:19_", "2012-10-29 19:50_", "2012-11-28 14:46n", "2012-12-28 10:21_", "2013-01-27 04:38_", "2013-02-25 20:26_", "2013-03-27 09:27_", "2013-04-25 19:57p", "2013-05-25 04:25n", "2013-06-23 11:32_", "2013-07-22 18:15_", "2013-08-21 01:45_", "2013-09-19 11:13_", "2013-10-18 23:38n", "2013-11-17 15:16_", "2013-12-17 09:28_", "2014-01-16 04:52_", "2014-02-14 23:53_", "2014-03-16 17:09_", "2014-04-15 07:42t", "2014-05-14 19:16_", "2014-06-13 04:11_", "2014-07-12 11:25_", "2014-08-10 18:09_", "2014-09-09 01:38_", "2014-10-08 10:51t", "2014-11-06 22:23_", "2014-12-06 12:27_", "2015-01-05 04:53_", "2015-02-03 23:09_", "2015-03-05 18:06_", "2015-04-04 12:06p", "2015-05-04 03:42_", "2015-06-02 16:19_", "2015-07-02 02:20_", "2015-07-31 10:43_", "2015-08-29 18:35_", "2015-09-28 02:50t", "2015-10-27 12:05_", "2015-11-25 22:44_", "2015-12-25 11:11_", "2016-01-24 01:46_", "2016-02-22 18:20_", "2016-03-23 12:01n", "2016-04-22 05:24_", "2016-05-21 21:15_", "2016-06-20 11:02_", "2016-07-19 22:57_", "2016-08-18 09:27_", "2016-09-16 19:05n", "2016-10-16 04:23_", "2016-11-14 13:52_", "2016-12-14 00:06_", "2017-01-12 11:34_", "2017-02-11 00:33n", "2017-03-12 14:54_", "2017-04-11 06:08_", "2017-05-10 21:43_", "2017-06-09 13:10_", "2017-07-09 04:07_", "2017-08-07 18:11p", "2017-09-06 07:03_", "2017-10-05 18:40_", "2017-11-04 05:23_", "2017-12-03 15:47_", "2018-01-02 02:24_", "2018-01-31 13:27t", "2018-03-02 00:51_", "2018-03-31 12:37_", "2018-04-30 00:58_", "2018-05-29 14:20_", "2018-06-28 04:53_", "2018-07-27 20:20t", "2018-08-26 11:56_", "2018-09-25 02:53_", "2018-10-24 16:45_", "2018-11-23 05:39_", "2018-12-22 17:49_")
        self.first_quarter_array = ("2008-01-15 19:46", "2008-02-14 03:34", "2008-03-14 10:46", "2008-04-12 18:32", "2008-05-12 03:47", "2008-06-10 15:04", "2008-07-10 04:35", "2008-08-08 20:20", "2008-09-07 14:04", "2008-10-07 09:04", "2008-11-06 04:04", "2008-12-05 21:26", "2009-01-04 11:56", "2009-02-02 23:13", "2009-03-04 07:46", "2009-04-02 14:34", "2009-05-01 20:44", "2009-05-31 03:22", "2009-06-29 11:28", "2009-07-28 22:00", "2009-08-27 11:42", "2009-09-26 04:50", "2009-10-26 00:42", "2009-11-24 21:39", "2009-12-24 17:36", "2010-01-23 10:53", "2010-02-22 00:42", "2010-03-23 11:00", "2010-04-21 18:20", "2010-05-20 23:43", "2010-06-19 04:30", "2010-07-18 10:11", "2010-08-16 18:14", "2010-09-15 05:50", "2010-10-14 21:27", "2010-11-13 16:39", "2010-12-13 13:59", "2011-01-12 11:31", "2011-02-11 07:18", "2011-03-12 23:45", "2011-04-11 12:05", "2011-05-10 20:33", "2011-06-09 02:11", "2011-07-08 06:29", "2011-08-06 11:08", "2011-09-04 17:39", "2011-10-04 03:15", "2011-11-02 16:38", "2011-12-02 09:52", "2012-01-01 06:15", "2012-01-31 04:10", "2012-03-01 01:22", "2012-03-30 19:41", "2012-04-29 09:58", "2012-05-28 20:16", "2012-06-27 03:30", "2012-07-26 08:56", "2012-08-24 13:54", "2012-09-22 19:41", "2012-10-22 03:32", "2012-11-20 14:31", "2012-12-20 05:19", "2013-01-18 23:45", "2013-02-17 20:31", "2013-03-19 17:27", "2013-04-18 12:31", "2013-05-18 04:35", "2013-06-16 17:24", "2013-07-16 03:18", "2013-08-14 10:56", "2013-09-12 17:08", "2013-10-11 23:02", "2013-11-10 05:57", "2013-12-09 15:12", "2014-01-08 03:39", "2014-02-06 19:22", "2014-03-08 13:27", "2014-04-07 08:31", "2014-05-07 03:15", "2014-06-05 20:39", "2014-07-05 11:59", "2014-08-04 00:50", "2014-09-02 11:11", "2014-10-01 19:33", "2014-10-31 02:48", "2014-11-29 10:06", "2014-12-28 18:31", "2015-01-27 04:48", "2015-02-25 17:14", "2015-03-27 07:43", "2015-04-25 23:55", "2015-05-25 17:19", "2015-06-24 11:03", "2015-07-24 04:04", "2015-08-22 19:31", "2015-09-21 08:59", "2015-10-20 20:31", "2015-11-19 06:27", "2015-12-18 15:14", "2016-01-16 23:26", "2016-02-15 07:46", "2016-03-15 17:03", "2016-04-14 03:59", "2016-05-13 17:02", "2016-06-12 08:10", "2016-07-12 00:52", "2016-08-10 18:21", "2016-09-09 11:49", "2016-10-09 04:33", "2016-11-07 19:51", "2016-12-07 09:03", "2017-01-05 19:47", "2017-02-04 04:19", "2017-03-05 11:32", "2017-04-03 18:39", "2017-05-03 02:47", "2017-06-01 12:42", "2017-07-01 00:51", "2017-07-30 15:23", "2017-08-29 08:13", "2017-09-28 02:54", "2017-10-27 22:22", "2017-11-26 17:03", "2017-12-26 09:20", "2018-01-24 22:20", "2018-02-23 08:09", "2018-03-24 15:35", "2018-04-22 21:46", "2018-05-22 03:49", "2018-06-20 10:51", "2018-07-19 19:52", "2018-08-18 07:49", "2018-09-16 23:15", "2018-10-16 18:02", "2018-11-15 14:54", "2018-12-15 11:49")
        self.last_quarter_array = ("2008-01-30 05:03", "2008-02-29 02:18", "2008-03-29 21:47", "2008-04-28 14:12", "2008-05-28 02:57", "2008-06-26 12:10", "2008-07-25 18:42", "2008-08-23 23:50", "2008-09-22 05:04", "2008-10-21 11:55", "2008-11-19 21:31", "2008-12-19 10:29", "2009-01-18 02:46", "2009-02-16 21:37", "2009-03-18 17:47", "2009-04-17 13:36", "2009-05-17 07:26", "2009-06-15 22:15", "2009-07-15 09:53", "2009-08-13 18:55", "2009-09-12 02:16", "2009-10-11 08:56", "2009-11-09 15:56", "2009-12-09 00:13", "2010-01-07 10:40", "2010-02-05 23:49", "2010-03-07 15:42", "2010-04-06 09:37", "2010-05-06 04:15", "2010-06-04 22:13", "2010-07-04 14:35", "2010-08-03 04:59", "2010-09-01 17:22", "2010-10-01 03:52", "2010-10-30 12:46", "2010-11-28 20:36", "2010-12-28 04:18", "2011-01-26 12:57", "2011-02-24 23:26", "2011-03-26 12:07", "2011-04-25 02:47", "2011-05-24 18:52", "2011-06-23 11:48", "2011-07-23 05:02", "2011-08-21 21:55", "2011-09-20 13:39", "2011-10-20 03:30", "2011-11-18 15:09", "2011-12-18 00:48", "2012-01-16 09:08", "2012-02-14 17:04", "2012-03-15 01:25", "2012-04-13 10:50", "2012-05-12 21:47", "2012-06-11 10:41", "2012-07-11 01:48", "2012-08-09 18:55", "2012-09-08 13:15", "2012-10-08 07:33", "2012-11-07 00:36", "2012-12-06 15:32", "2013-01-05 03:58", "2013-02-03 13:56", "2013-03-04 21:53", "2013-04-03 04:37", "2013-05-02 11:14", "2013-05-31 18:58", "2013-06-30 04:54", "2013-07-29 17:43", "2013-08-28 09:35", "2013-09-27 03:56", "2013-10-26 23:41", "2013-11-25 19:28", "2013-12-25 13:48", "2014-01-24 05:19", "2014-02-22 17:15", "2014-03-24 01:46", "2014-04-22 07:52", "2014-05-21 12:59", "2014-06-19 18:39", "2014-07-19 02:08", "2014-08-17 12:26", "2014-09-16 02:05", "2014-10-15 19:12", "2014-11-14 15:16", "2014-12-14 12:51", "2015-01-13 09:47", "2015-02-12 03:50", "2015-03-13 17:48", "2015-04-12 03:44", "2015-05-11 10:36", "2015-06-09 15:42", "2015-07-08 20:24", "2015-08-07 02:03", "2015-09-05 09:54", "2015-10-04 21:06", "2015-11-03 12:24", "2015-12-03 07:40", "2016-01-02 05:30", "2016-02-01 03:28", "2016-03-01 23:11", "2016-03-31 15:17", "2016-04-30 03:29", "2016-05-29 12:12", "2016-06-27 18:19", "2016-07-26 23:00", "2016-08-25 03:41", "2016-09-23 09:56", "2016-10-22 19:14", "2016-11-21 08:33", "2016-12-21 01:56", "2017-01-19 22:14", "2017-02-18 19:33", "2017-03-20 15:58", "2017-04-19 09:57", "2017-05-19 00:33", "2017-06-17 11:33", "2017-07-16 19:26", "2017-08-15 01:15", "2017-09-13 06:25", "2017-10-12 12:25", "2017-11-10 20:37", "2017-12-10 07:51", "2018-01-08 22:25", "2018-02-07 15:54", "2018-03-09 11:20", "2018-04-08 07:18", "2018-05-08 02:09", "2018-06-06 18:32", "2018-07-06 07:51", "2018-08-04 18:18", "2018-09-03 02:37", "2018-10-02 09:45", "2018-10-31 16:40", "2018-11-30 00:19", "2018-12-29 09:34")

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
        self.next_lunar_eclipse_sec = self.next_lunar_eclipse_sec_at_time(the_date)
        self.next_solar_eclipse_sec = self.next_solar_eclipse_sec_at_time(the_date)
        self.last_lunar_eclipse_sec = self.last_lunar_eclipse_sec_at_time(the_date)
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
                    return next - now
        return -1

    def last_lunar_eclipse_sec_at_time(self, now):
        """Return (positive) seconds to the last Lunar eclipe or -1.
        """
        last = -1
        for date_string in self.full_moon_array:
            if date_string[-1:] != "_":
                then = time.mktime(time.strptime(date_string[:-1], self.date_format))
                if then >= now:
                    break
                last = then
        if last == -1:
            return -1
        else:
            return now - last

    def next_solar_eclipse_sec_at_time(self, now):
        """Return (positive) seconds to the next Solar eclipe or -1.
        """
        for date_string in self.new_moon_array:
            if date_string[-1:] != "_":
                next = time.mktime(time.strptime(date_string[:-1], self.date_format))
                if next >= now:
                    return next - now
        return -1
