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

"""\
Moon phase information XO activity.

TODO:
- Mouse over text hints for major Moon features
- Reduce amount of decimal places shown
  - remove seconds and/or minutes?
  - make basic text info (phase) more central/larger (show mini-graphic)?
  - make complex text info less prominent?
  - allow hiding of different information blocks?
    - make info area scrollable so more could be included?
- When showing grid, draw terminator in green?
- Would a move to Cairo allow me better alpha control?
- Show daylight view menu option?
  - fades out moon during the (approx) day with pastel blue
  - eye candy cloud effect?
  - solar eclipse effect
- Show interesting markers view menu option?
  - lunar probes
  - man missions
- Structure code into a better View, Model, Controller
- Reduce CPU and memory footprint
  - stop updates when the activity is not visible
  - free up (mainly image) data between updates or when not visible?
- Wrap 'Next' dates in round rect bezel style with mini Moon graphic?
- New feature, mini-month calendar view in bottom of info area?
- Dark adapted view for night gazing usage?
"""

import gtk
import gobject
from sugar.activity import activity
from sugar.graphics.toolbutton import ToolButton
from gettext import gettext as _
import math
import time
import json
import os

IMAGE_SIZE = 726
HALF_SIZE = IMAGE_SIZE / 2

class MoonActivity(activity.Activity):
    """Moon phase activity."""
    def __init__(self, handle):
        activity.Activity.__init__(self, handle)
        self._name = handle
        self.set_title(_("Moon"))
        
        # Defaults (Journal resume priority, default persistent file secondary, fall-back hardcoded values)
        self.hemisphereView = 'north'
        self.showGrid = False
        self.activityState = {}
        self.activityState['hemisphereView'] = self.hemisphereView
        self.activityState['showGrid'] = self.showGrid
        self.read_and_parse_preferences(os.environ['SUGAR_ACTIVITY_ROOT'] + '/data/defaults')
                
        # Toolbox
        toolbox = activity.ActivityToolbox(self)
        viewToolBar = gtk.Toolbar()
        self.toggleGridButton = ToolButton('grid-icon')
        self.toggleGridButton.set_tooltip(_("Toggle Grid View"))
        self.toggleGridHandlerId = self.toggleGridButton.connect('clicked', self.toggle_grid_clicked)
        viewToolBar.insert(self.toggleGridButton, -1)
        self.toggleGridButton.show()
        self.toggleHemisphereButton = ToolButton('hemi-icon')
        self.toggleHemisphereButton.set_tooltip(_("Toggle Hemisphere View"))
        self.toggleHemisphereHandlerId = self.toggleHemisphereButton.connect('clicked', self.toggle_hemisphere_clicked)
        viewToolBar.insert(self.toggleHemisphereButton, -1)
        self.toggleHemisphereButton.show()
        viewToolBar.show()
        toolbox.add_toolbar(_('View'), viewToolBar)
        self.set_toolbox(toolbox)
        toolbox.show()

        # Create the main activity container
        self.mainView = gtk.HBox()

        # Create event box to hold Moon image (so I can set background color)
        self.event_box = gtk.EventBox()
        colormap = gtk.gdk.colormap_get_system()
        self.blackAllocColor = colormap.alloc_color('black')
        self.whiteAllocColor = colormap.alloc_color('white')
        self.blueGreenMaskAllocColor = colormap.alloc_color('#F00')
        self.redAllocColor = colormap.alloc_color('#F20')
        self.blueAllocColor = colormap.alloc_color('#04F')
        self.event_box.modify_bg(gtk.STATE_NORMAL, self.blackAllocColor)
        
        # Create the Moon image widget
        self.image = gtk.Image()
        self.imagePixmap = gtk.gdk.Pixmap(self.window, IMAGE_SIZE, IMAGE_SIZE)
        self.gc = self.imagePixmap.new_gc(foreground=self.blackAllocColor)
        self.image.set_from_pixmap(self.imagePixmap, None)
        self.event_box.add(self.image)
        self.mainView.pack_end(self.event_box)
        
        # Create Moon information panel
        self.infoPanel = gtk.VBox()
        self.infoPanel.set_border_width(17)
        self.info = gtk.Label()
        self.info.set_justify(gtk.JUSTIFY_LEFT)
        self.infoPanel.pack_start(self.info, False, False, 0)
        self.mainView.pack_start(self.infoPanel, False, False, 0)

        # Create Moon data model
        self.dataModel = DataModel()

        # Generate first set of views for display and kick off their timers
        self.toggleGridButton.handler_block(self.toggleGridHandlerId)
        self.toggleHemisphereButton.handler_block(self.toggleHemisphereHandlerId)
        self.update_text_information_view()
        self.update_moon_image_view()

        # Display everything
        self.info.show()
        self.infoPanel.show()
        self.image.show()
        self.event_box.show()
        self.mainView.show()
        self.set_canvas(self.mainView)
        self.show_all()

    def read_and_parse_preferences(self, file_path):
        """Parse and set preference data from a given file."""
        try:
            readFile = open(file_path, 'r')
            self.activityState = json.read(readFile.read())
            if self.activityState.has_key('hemisphereView'):
                self.hemisphereView = self.activityState['hemisphereView']
            if self.activityState.has_key('showGrid'):
                self.showGrid = self.activityState['showGrid']
            readFile.close()
        except:
            pass

    def read_file(self, file_path):
        """Read state from datastore."""
        self.read_and_parse_preferences(file_path)
        self.block_view_buttons_during_update()
        
    def write_file(self, file_path):
        """Write state to journal datastore and to persistent file system."""
        self.activityState['hemisphereView'] = self.hemisphereView
        self.activityState['showGrid'] = self.showGrid
        serialisedData = json.write(self.activityState)
        
        toJournal = file(file_path, 'w')
        try:
            toJournal.write(serialisedData)
        finally:
            toJournal.close()
            
        toPersistentFs = file(os.environ['SUGAR_ACTIVITY_ROOT'] + '/data/defaults', 'w')
        try:
            toPersistentFs.write(serialisedData)
        finally:
            toPersistentFs.close()
    
    def toggle_grid_clicked(self, widget):
        """Respond to toolbar button to hide/show grid lines."""
        if self.showGrid == True:
            self.showGrid = False
        else:
            self.showGrid = True
        self.block_view_buttons_during_update()

    def toggle_hemisphere_clicked(self, widget):
        """Respond to toolbar button to change viewing hemisphere."""
        if self.hemisphereView == 'north':
            self.hemisphereView = 'south'
        else:
            self.hemisphereView = 'north'
        self.block_view_buttons_during_update()

    def block_view_buttons_during_update(self):
        """Disable view buttons while updating image to prevent multi-clicks."""
        self.toggleGridButton.handler_block(self.toggleGridHandlerId)
        self.toggleHemisphereButton.handler_block(self.toggleHemisphereHandlerId)
        gobject.source_remove(self.updateMoonImageTimeout)
        self.update_moon_image_view()

    def unblock_view_update_buttons(self):
        """Reactivate view button after updating image, stops multi-clicks."""
        self.toggleGridButton.handler_unblock(self.toggleGridHandlerId)
        self.toggleHemisphereButton.handler_unblock(self.toggleHemisphereHandlerId)
        
    def update_text_information_view(self):
        """Generate Moon data and update text based information view."""
        # Generate Moon data
        self.dataModel.update_moon_calculations(time.time())

        # Update text information
        informationString = ""
        informationString += _("Today's Moon Information\n\n")
        informationString += _("Phase:\n%s\n\n") % (self.dataModel.moon_phase_name(self.dataModel.phaseOfMoon))
        informationString += _("Julian Date:\n%.2f (astronomical)\n\n") % (self.dataModel.julianDate)
        informationString += _("Age:\n%(days).0f days, %(hours).0f hours, %(minutes).0f minutes\n\n") % {'days':self.dataModel.daysOld, 'hours':self.dataModel.hoursOld, 'minutes':self.dataModel.minutesOld}
        informationString += _("Lunation:\n%(phase).2f%% through lunation %(lunation)d\n\n") % {'phase':self.dataModel.phaseOfMoon * 100, 'lunation':self.dataModel.lunation}
        informationString += _("Surface Visibility:\n%.0f%% (estimated)\n\n") % (self.dataModel.percentOfFullMoon * 100)
        informationString += _("Selenographic Terminator Longitude:\n%(deg).1f˚%(westOrEast)s (%(riseOrSet)s)\n\n") % {'deg':self.dataModel.selenographicDeg, 'westOrEast':self.dataModel.westOrEast, 'riseOrSet':self.dataModel.riseOrSet}
        informationString += _("Next Full Moon:\n%(date)s in %(days).0f days\n\n") % {'date':time.ctime(self.dataModel.nextFullMoonDate), 'days':self.dataModel.daysUntilFullMoon}
        informationString += _("Next New Moon:\n%(date)s in %(days).0f days\n\n") % {'date':time.ctime(self.dataModel.nextNewMoonDate), 'days':self.dataModel.daysUntilNewMoon}
        informationString += _("Next Lunar eclipse:\n%(date)s in %(days).0f days\n\n") % {'date':time.ctime(self.dataModel.nextLunarEclipseDate), 'days':self.dataModel.daysUntilLunarEclipse}
        informationString += _("Next Solar eclipse:\n%(date)s in %(days).0f days\n\n") % {'date':time.ctime(self.dataModel.nextSolarEclipseDate), 'days':self.dataModel.daysUntilSolarEclipse}
        self.info.set_markup(informationString)

        # Calculate time to next minute cusp and set a new timer
        msToNextMinCusp = (60 - time.gmtime()[5]) * 1000
        gobject.timeout_add(msToNextMinCusp, self.update_text_information_view)

        # Stop this timer running
        return False

    def update_moon_image_view(self):
        """Update Moon image view using last cached Moon data."""
        # Erase last Moon rendering
        self.imagePixmap.draw_rectangle(self.gc, True, 0, 0, IMAGE_SIZE, IMAGE_SIZE)
                
        # Create a 1bit shadow mask
        maskPixmap = gtk.gdk.Pixmap(None, IMAGE_SIZE, IMAGE_SIZE, depth=1)
        kgc = maskPixmap.new_gc(foreground=self.blackAllocColor)
        wgc = maskPixmap.new_gc(foreground=self.whiteAllocColor)
        maskPixmap.draw_rectangle(kgc, True, 0, 0, IMAGE_SIZE, IMAGE_SIZE)
        if self.dataModel.phaseOfMoon <= .25:
            # New Moon to First Quarter
            phaseShadowAdjust = self.dataModel.phaseOfMoon - abs(math.sin(self.dataModel.phaseOfMoon * math.pi * 4) / 18.0)
            arcScale = int(IMAGE_SIZE * (1 - (phaseShadowAdjust * 4)))
            maskPixmap.draw_rectangle(wgc, True, HALF_SIZE + 1, 0, HALF_SIZE, IMAGE_SIZE - 1)
            maskPixmap.draw_arc(kgc, True, HALF_SIZE - int(arcScale / 2), 0, arcScale, IMAGE_SIZE, 17280, 11520)
        elif self.dataModel.phaseOfMoon <= .5:
            # First Quarter to Full Moon
            phaseShadowAdjust = self.dataModel.phaseOfMoon + abs(math.sin(self.dataModel.phaseOfMoon * math.pi * 4) / 18.0)
            arcScale = int(IMAGE_SIZE * ((phaseShadowAdjust - .25) * 4))
            maskPixmap.draw_rectangle(wgc, True, HALF_SIZE, 0, HALF_SIZE, IMAGE_SIZE)
            maskPixmap.draw_arc(wgc, True, HALF_SIZE - int(arcScale / 2), 0, arcScale, IMAGE_SIZE, 5760, 11520)
        elif self.dataModel.phaseOfMoon <= .75:
            # Full Moon to Last Quarter
            phaseShadowAdjust = self.dataModel.phaseOfMoon - abs(math.sin(self.dataModel.phaseOfMoon * math.pi * 4) / 18.0)
            arcScale = int(IMAGE_SIZE * (1 - ((phaseShadowAdjust - .5) * 4)))
            maskPixmap.draw_rectangle(wgc, True, 0, 0, HALF_SIZE + 1, IMAGE_SIZE)
            maskPixmap.draw_arc(wgc, True, HALF_SIZE - int(arcScale / 2), 0, arcScale, IMAGE_SIZE, 17280, 11520)
        else:
            # Last Quarter to New Moon
            phaseShadowAdjust = self.dataModel.phaseOfMoon + abs(math.sin(self.dataModel.phaseOfMoon * math.pi * 4) / 18.0)
            arcScale = int(IMAGE_SIZE * ((phaseShadowAdjust - .75) * 4))
            maskPixmap.draw_rectangle(wgc, True, 0, 0, HALF_SIZE, IMAGE_SIZE)
            maskPixmap.draw_arc(kgc, True, HALF_SIZE - int(arcScale / 2), 0, arcScale, IMAGE_SIZE, 5760, 11520)
        maskgc = self.imagePixmap.new_gc(clip_mask=maskPixmap)
        
        # Modified image based on public domain photo by John MacCooey
        moonPixbuf = gtk.gdk.pixbuf_new_from_file("moon.jpg")

        # Composite bright Moon image and semi-transparant Moon for shadow detail
        darkPixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, IMAGE_SIZE, IMAGE_SIZE)
        if (self.dataModel.nextLunarEclipseSeconds == -1 and self.dataModel.lastLunarEclipseSeconds > 7200) or (self.dataModel.nextLunarEclipseSeconds > 7200 and self.dataModel.lastLunarEclipseSeconds == -1) or min(self.dataModel.nextLunarEclipseSeconds, self.dataModel.lastLunarEclipseSeconds) > 7200:
            # Normal Moon phase render
            moonPixbuf.composite(darkPixbuf, 0, 0, IMAGE_SIZE, IMAGE_SIZE, 0, 0, 1, 1, gtk.gdk.INTERP_BILINEAR, 127)
            self.imagePixmap.draw_pixbuf(self.gc, darkPixbuf, 0, 0, 0, 0)
            self.imagePixmap.draw_pixbuf(maskgc, moonPixbuf, 0, 0, 0, 0)

        else:
            # Reddening eclipse effect, 2hrs (7200sec) before and after (by masking out green & blue)
            if self.dataModel.nextLunarEclipseSeconds == -1:
                eclipseAlpha = self.dataModel.lastLunarEclipseSeconds / 7200.0 * 256
            elif self.dataModel.lastLunarEclipseSeconds == -1:
                eclipseAlpha = self.dataModel.nextLunarEclipseSeconds / 7200.0 * 256
            else:
                eclipseAlpha = min(self.dataModel.nextLunarEclipseSeconds, self.dataModel.lastLunarEclipseSeconds) / 7200.0 * 256
            moonPixbuf.composite(darkPixbuf, 0, 0, IMAGE_SIZE, IMAGE_SIZE, 0, 0, 1, 1, gtk.gdk.INTERP_BILINEAR, 196 - eclipseAlpha / 2)
            self.imagePixmap.draw_pixbuf(self.gc, darkPixbuf, 0, 0, 0, 0)
            del darkPixbuf
            darkPixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, IMAGE_SIZE, IMAGE_SIZE)
            moonPixbuf.composite(darkPixbuf, 0, 0, IMAGE_SIZE, IMAGE_SIZE, 0, 0, 1, 1, gtk.gdk.INTERP_BILINEAR, eclipseAlpha)
            rgc = self.imagePixmap.new_gc(foreground=self.blueGreenMaskAllocColor, function=gtk.gdk.AND)
            self.imagePixmap.draw_rectangle(rgc, True, 0, 0, IMAGE_SIZE, IMAGE_SIZE)
            self.imagePixmap.draw_pixbuf(self.gc, darkPixbuf, 0, 0, 0, 0)

        if self.hemisphereView == 'south':
            # Rotate final image for a view from north or south hemisphere
            rotPixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8, IMAGE_SIZE, IMAGE_SIZE)
            rotPixbuf.get_from_drawable(self.imagePixmap, self.imagePixmap.get_colormap(), 0, 0, 0, 0, -1, -1)
            rotPixbuf = rotPixbuf.rotate_simple(gtk.gdk.PIXBUF_ROTATE_UPSIDEDOWN)
            self.imagePixmap.draw_pixbuf(self.gc, rotPixbuf, 0, 0, 0, 0)
            if self.showGrid:
                # Draw grid rotated for south hemi
                self.draw_grid(_("SNWE"))
        elif self.showGrid:
            # Draw grid for north hemi
            self.draw_grid(_("NSEW"))

        self.image.queue_draw()

        # Update the Moon image in another 5min
        self.updateMoonImageTimeout = gobject.timeout_add(300000, self.update_moon_image_view)
        
        # Delay before view buttons can be clicked again (blocked to stop repeat clicks)
        gobject.timeout_add(50, self.unblock_view_update_buttons)

        # Stop this timer running
        return False

    def draw_grid(self, compassText):
        # Draw Selenographic grid line data
        rgc = self.imagePixmap.new_gc(foreground=self.redAllocColor)
        bgc = self.imagePixmap.new_gc(foreground=self.blueAllocColor)
        wgc = self.imagePixmap.new_gc(foreground=self.whiteAllocColor)
        pangoLayout = self.image.create_pango_layout("")
        pangoLayout.set_text("0°")
        self.imagePixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, HALF_SIZE, 24, 22)            
        self.imagePixmap.draw_layout(wgc, HALF_SIZE + 2, HALF_SIZE, pangoLayout)            
        pangoLayout.set_text("30°")
        self.imagePixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 0.5), 36, 22)            
        self.imagePixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 1.5), 36, 22)            
        self.imagePixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 0.5), pangoLayout)            
        self.imagePixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 1.5), pangoLayout)            
        pangoLayout.set_text("60°")
        self.imagePixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 0.15), 36, 22)            
        self.imagePixmap.draw_rectangle(bgc, True, HALF_SIZE + 2, int(HALF_SIZE * 1.85), 36, 22)            
        self.imagePixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 0.15), pangoLayout)            
        self.imagePixmap.draw_layout(wgc, HALF_SIZE + 2, int(HALF_SIZE * 1.85), pangoLayout)            
        pangoLayout.set_text("30°")
        self.imagePixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 0.48) + 2, HALF_SIZE, 36, 22)            
        self.imagePixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 1.52) + 2, HALF_SIZE, 36, 22)            
        self.imagePixmap.draw_layout(wgc, int(HALF_SIZE * 0.48) + 2, HALF_SIZE, pangoLayout)            
        self.imagePixmap.draw_layout(wgc, int(HALF_SIZE * 1.52) + 2, HALF_SIZE, pangoLayout)            
        pangoLayout.set_text("60°")
        self.imagePixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 0.15) + 2, HALF_SIZE, 36, 22)            
        self.imagePixmap.draw_rectangle(rgc, True, int(HALF_SIZE * 1.85) + 2, HALF_SIZE, 36, 22)            
        self.imagePixmap.draw_layout(wgc, int(HALF_SIZE * 0.15) + 2, HALF_SIZE, pangoLayout)            
        self.imagePixmap.draw_layout(wgc, int(HALF_SIZE * 1.85) + 2, HALF_SIZE, pangoLayout)            
        for i in (-1, 0, 1):
            self.imagePixmap.draw_line(rgc, HALF_SIZE + i, 0, HALF_SIZE + i, IMAGE_SIZE)
            self.imagePixmap.draw_arc(rgc, False, int(HALF_SIZE * 0.15) + i, 0, IMAGE_SIZE - int(IMAGE_SIZE * 0.15), IMAGE_SIZE, 0, 360*64)
            self.imagePixmap.draw_arc(rgc, False, int(HALF_SIZE * 0.48) + i, 0, IMAGE_SIZE - int(IMAGE_SIZE * 0.48) , IMAGE_SIZE, 0, 360*64)
            self.imagePixmap.draw_line(bgc, 0, HALF_SIZE + i, IMAGE_SIZE, HALF_SIZE + i)
            self.imagePixmap.draw_line(bgc, int(HALF_SIZE * 0.15), int(HALF_SIZE * 0.5) + i, IMAGE_SIZE - int(HALF_SIZE * 0.15), int(HALF_SIZE * 0.5) + i)
            self.imagePixmap.draw_line(bgc, int(HALF_SIZE * 0.15), int(HALF_SIZE * 1.5) + i, IMAGE_SIZE - int(HALF_SIZE * 0.15), int(HALF_SIZE * 1.5) + i)
            self.imagePixmap.draw_line(bgc, int(HALF_SIZE * 0.5), int(HALF_SIZE * 0.15) + i, IMAGE_SIZE - int(HALF_SIZE * 0.5), int(HALF_SIZE * 0.15) + i)
            self.imagePixmap.draw_line(bgc, int(HALF_SIZE * 0.5), int(HALF_SIZE * 1.85) + i, IMAGE_SIZE - int(HALF_SIZE * 0.5), int(HALF_SIZE * 1.85) + i)

        # Key text
        pangoLayout.set_text(_("Latitude"))
        self.imagePixmap.draw_layout(bgc, 0, IMAGE_SIZE - 48, pangoLayout)
        pangoLayout.set_text(_("Longitude"))
        self.imagePixmap.draw_layout(rgc, 0, IMAGE_SIZE - 24, pangoLayout)

        # Compass
        self.imagePixmap.draw_line(bgc, 45, 24, 45, 68)
        self.imagePixmap.draw_line(rgc, 22, 48, 68, 48)
        pangoLayout.set_text(compassText[0])
        self.imagePixmap.draw_layout(bgc, 38, 0, pangoLayout)
        pangoLayout.set_text(compassText[1])
        self.imagePixmap.draw_layout(bgc, 38, 72, pangoLayout)
        pangoLayout.set_text(compassText[2])
        self.imagePixmap.draw_layout(rgc, 72, 36, pangoLayout)
        pangoLayout.set_text(compassText[3])
        self.imagePixmap.draw_layout(rgc, 0, 36, pangoLayout)
        

class DataModel():
    """Moon phase data model and various utility methods."""
    
    def __init__(self):
        """Init simple, hard coded, tupules for New, First Quarter, Full Last Quarter Moon UTC data.
        
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
        _=none."""
        
        self.dateFormat = "%Y-%m-%d %H:%M"
        self.newMoonArray = ("2008-01-08 11:37_", "2008-02-07 03:44A", "2008-03-07 17:14_", "2008-04-06 03:55_", "2008-05-05 12:18_", "2008-06-03 19:23_", "2008-07-03 02:19_", "2008-08-01 10:13T", "2008-08-30 19:58_", "2008-09-29 08:12_", "2008-10-28 23:14_", "2008-11-27 16:55_", "2008-12-27 12:23_", "2009-01-26 07:55A", "2009-02-25 01:35_", "2009-03-26 16:06_", "2009-04-25 03:23_", "2009-05-24 12:11_", "2009-06-22 19:35_", "2009-07-22 02:35T", "2009-08-20 10:01_", "2009-09-18 18:44_", "2009-10-18 05:33_", "2009-11-16 19:14_", "2009-12-16 12:02_", "2010-01-15 07:11A", "2010-02-14 02:51_", "2010-03-15 21:01_", "2010-04-14 12:29_", "2010-05-14 01:04_", "2010-06-12 11:15_", "2010-07-11 19:40T", "2010-08-10 03:08_", "2010-09-08 10:30_", "2010-10-07 18:44_", "2010-11-06 04:52_", "2010-12-05 17:36_", "2011-01-04 09:03P", "2011-02-03 02:31_", "2011-03-04 20:46_", "2011-04-03 14:32_", "2011-05-03 06:51_", "2011-06-01 21:03P", "2011-07-01 08:54P", "2011-07-30 18:40_", "2011-08-29 03:04_", "2011-09-27 11:09_", "2011-10-26 19:56_", "2011-11-25 06:10P", "2011-12-24 18:06_", "2012-01-23 07:39_", "2012-02-21 22:35_", "2012-03-22 14:37_", "2012-04-21 07:18_", "2012-05-20 23:47A", "2012-06-19 15:02_", "2012-07-19 04:24_", "2012-08-17 15:54_", "2012-09-16 02:11_", "2012-10-15 12:02_", "2012-11-13 22:08T", "2012-12-13 08:42_", "2013-01-11 19:44_", "2013-02-10 07:20_", "2013-03-11 19:51_", "2013-04-10 09:35_", "2013-05-10 00:29A", "2013-06-08 15:56_", "2013-07-08 07:14_", "2013-08-06 21:51_", "2013-09-05 11:36_", "2013-10-05 00:35_", "2013-11-03 12:50H", "2013-12-03 00:22_", "2014-01-01 11:14_", "2014-01-30 21:39_", "2014-03-01 08:00_", "2014-03-30 18:45_", "2014-04-29 06:14A", "2014-05-28 18:40_", "2014-06-27 08:09_", "2014-07-26 22:42_", "2014-08-25 14:13_", "2014-09-24 06:14_", "2014-10-23 21:57P", "2014-11-22 12:32_", "2014-12-22 01:36_", "2015-01-20 13:14_", "2015-02-18 23:47_", "2015-03-20 09:36T", "2015-04-18 18:57_", "2015-05-18 04:13_", "2015-06-16 14:05_", "2015-07-16 01:24_", "2015-08-14 14:54_", "2015-09-13 06:41P", "2015-10-13 00:06_", "2015-11-11 17:47_", "2015-12-11 10:29_", "2016-01-10 01:30_", "2016-02-08 14:39_", "2016-03-09 01:54T", "2016-04-07 11:24_", "2016-05-06 19:30_", "2016-06-05 03:00_", "2016-07-04 11:01_", "2016-08-02 20:45_", "2016-09-01 09:03A", "2016-10-01 00:12_", "2016-10-30 17:38_", "2016-11-29 12:18_", "2016-12-29 06:53_", "2017-01-28 00:07_", "2017-02-26 14:58A", "2017-03-28 02:57_", "2017-04-26 12:16_", "2017-05-25 19:44_", "2017-06-24 02:31_", "2017-07-23 09:46_", "2017-08-21 18:30T", "2017-09-20 05:30_", "2017-10-19 19:12_", "2017-11-18 11:42_", "2017-12-18 06:31_", "2018-01-17 02:17_", "2018-02-15 21:05P", "2018-03-17 13:12_", "2018-04-16 01:57_", "2018-05-15 11:48_", "2018-06-13 19:43_", "2018-07-13 02:48P", "2018-08-11 09:58P", "2018-09-09 18:01_", "2018-10-09 03:47_", "2018-11-07 16:02_", "2018-12-07 07:20_")
        self.fullMoonArray = ("2008-01-22 13:35_", "2008-02-21 03:31t", "2008-03-21 18:40_", "2008-04-20 10:25_", "2008-05-20 02:11_", "2008-06-18 17:30_", "2008-07-18 07:59_", "2008-08-16 21:16p", "2008-09-15 09:13_", "2008-10-14 20:03_", "2008-11-13 06:17_", "2008-12-12 16:37_", "2009-01-11 03:27_", "2009-02-09 14:49n", "2009-03-11 02:38_", "2009-04-09 14:56_", "2009-05-09 04:01_", "2009-06-07 18:12_", "2009-07-07 09:21n", "2009-08-06 00:55n", "2009-09-04 16:03_", "2009-10-04 06:10_", "2009-11-02 19:14_", "2009-12-02 07:30_", "2009-12-31 19:13p", "2010-01-30 06:18_", "2010-02-28 16:38_", "2010-03-30 02:25_", "2010-04-28 12:18_", "2010-05-27 23:07_", "2010-06-26 11:30p", "2010-07-26 01:37_", "2010-08-24 17:05_", "2010-09-23 09:17_", "2010-10-23 01:36_", "2010-11-21 17:27_", "2010-12-21 08:13t", "2011-01-19 21:21_", "2011-02-18 08:36_", "2011-03-19 18:10_", "2011-04-18 02:44_", "2011-05-17 11:09_", "2011-06-15 20:13t", "2011-07-15 06:40_", "2011-08-13 18:58_", "2011-09-12 09:27_", "2011-10-12 02:06_", "2011-11-10 20:16_", "2011-12-10 14:36t", "2012-01-09 07:30_", "2012-02-07 21:54_", "2012-03-08 09:40_", "2012-04-06 19:19_", "2012-05-06 03:35_", "2012-06-04 11:12p", "2012-07-03 18:52_", "2012-08-02 03:27_", "2012-08-31 13:58_", "2012-09-30 03:19_", "2012-10-29 19:50_", "2012-11-28 14:46n", "2012-12-28 10:21_", "2013-01-27 04:38_", "2013-02-25 20:26_", "2013-03-27 09:27_", "2013-04-25 19:57p", "2013-05-25 04:25n", "2013-06-23 11:32_", "2013-07-22 18:15_", "2013-08-21 01:45_", "2013-09-19 11:13_", "2013-10-18 23:38n", "2013-11-17 15:16_", "2013-12-17 09:28_", "2014-01-16 04:52_", "2014-02-14 23:53_", "2014-03-16 17:09_", "2014-04-15 07:42t", "2014-05-14 19:16_", "2014-06-13 04:11_", "2014-07-12 11:25_", "2014-08-10 18:09_", "2014-09-09 01:38_", "2014-10-08 10:51t", "2014-11-06 22:23_", "2014-12-06 12:27_", "2015-01-05 04:53_", "2015-02-03 23:09_", "2015-03-05 18:06_", "2015-04-04 12:06p", "2015-05-04 03:42_", "2015-06-02 16:19_", "2015-07-02 02:20_", "2015-07-31 10:43_", "2015-08-29 18:35_", "2015-09-28 02:50t", "2015-10-27 12:05_", "2015-11-25 22:44_", "2015-12-25 11:11_", "2016-01-24 01:46_", "2016-02-22 18:20_", "2016-03-23 12:01n", "2016-04-22 05:24_", "2016-05-21 21:15_", "2016-06-20 11:02_", "2016-07-19 22:57_", "2016-08-18 09:27_", "2016-09-16 19:05n", "2016-10-16 04:23_", "2016-11-14 13:52_", "2016-12-14 00:06_", "2017-01-12 11:34_", "2017-02-11 00:33n", "2017-03-12 14:54_", "2017-04-11 06:08_", "2017-05-10 21:43_", "2017-06-09 13:10_", "2017-07-09 04:07_", "2017-08-07 18:11p", "2017-09-06 07:03_", "2017-10-05 18:40_", "2017-11-04 05:23_", "2017-12-03 15:47_", "2018-01-02 02:24_", "2018-01-31 13:27t", "2018-03-02 00:51_", "2018-03-31 12:37_", "2018-04-30 00:58_", "2018-05-29 14:20_", "2018-06-28 04:53_", "2018-07-27 20:20t", "2018-08-26 11:56_", "2018-09-25 02:53_", "2018-10-24 16:45_", "2018-11-23 05:39_", "2018-12-22 17:49_")
        self.firstQuarterArray = ("2008-01-15 19:46", "2008-02-14 03:34", "2008-03-14 10:46", "2008-04-12 18:32", "2008-05-12 03:47", "2008-06-10 15:04", "2008-07-10 04:35", "2008-08-08 20:20", "2008-09-07 14:04", "2008-10-07 09:04", "2008-11-06 04:04", "2008-12-05 21:26", "2009-01-04 11:56", "2009-02-02 23:13", "2009-03-04 07:46", "2009-04-02 14:34", "2009-05-01 20:44", "2009-05-31 03:22", "2009-06-29 11:28", "2009-07-28 22:00", "2009-08-27 11:42", "2009-09-26 04:50", "2009-10-26 00:42", "2009-11-24 21:39", "2009-12-24 17:36", "2010-01-23 10:53", "2010-02-22 00:42", "2010-03-23 11:00", "2010-04-21 18:20", "2010-05-20 23:43", "2010-06-19 04:30", "2010-07-18 10:11", "2010-08-16 18:14", "2010-09-15 05:50", "2010-10-14 21:27", "2010-11-13 16:39", "2010-12-13 13:59", "2011-01-12 11:31", "2011-02-11 07:18", "2011-03-12 23:45", "2011-04-11 12:05", "2011-05-10 20:33", "2011-06-09 02:11", "2011-07-08 06:29", "2011-08-06 11:08", "2011-09-04 17:39", "2011-10-04 03:15", "2011-11-02 16:38", "2011-12-02 09:52", "2012-01-01 06:15", "2012-01-31 04:10", "2012-03-01 01:22", "2012-03-30 19:41", "2012-04-29 09:58", "2012-05-28 20:16", "2012-06-27 03:30", "2012-07-26 08:56", "2012-08-24 13:54", "2012-09-22 19:41", "2012-10-22 03:32", "2012-11-20 14:31", "2012-12-20 05:19", "2013-01-18 23:45", "2013-02-17 20:31", "2013-03-19 17:27", "2013-04-18 12:31", "2013-05-18 04:35", "2013-06-16 17:24", "2013-07-16 03:18", "2013-08-14 10:56", "2013-09-12 17:08", "2013-10-11 23:02", "2013-11-10 05:57", "2013-12-09 15:12", "2014-01-08 03:39", "2014-02-06 19:22", "2014-03-08 13:27", "2014-04-07 08:31", "2014-05-07 03:15", "2014-06-05 20:39", "2014-07-05 11:59", "2014-08-04 00:50", "2014-09-02 11:11", "2014-10-01 19:33", "2014-10-31 02:48", "2014-11-29 10:06", "2014-12-28 18:31", "2015-01-27 04:48", "2015-02-25 17:14", "2015-03-27 07:43", "2015-04-25 23:55", "2015-05-25 17:19", "2015-06-24 11:03", "2015-07-24 04:04", "2015-08-22 19:31", "2015-09-21 08:59", "2015-10-20 20:31", "2015-11-19 06:27", "2015-12-18 15:14", "2016-01-16 23:26", "2016-02-15 07:46", "2016-03-15 17:03", "2016-04-14 03:59", "2016-05-13 17:02", "2016-06-12 08:10", "2016-07-12 00:52", "2016-08-10 18:21", "2016-09-09 11:49", "2016-10-09 04:33", "2016-11-07 19:51", "2016-12-07 09:03", "2017-01-05 19:47", "2017-02-04 04:19", "2017-03-05 11:32", "2017-04-03 18:39", "2017-05-03 02:47", "2017-06-01 12:42", "2017-07-01 00:51", "2017-07-30 15:23", "2017-08-29 08:13", "2017-09-28 02:54", "2017-10-27 22:22", "2017-11-26 17:03", "2017-12-26 09:20", "2018-01-24 22:20", "2018-02-23 08:09", "2018-03-24 15:35", "2018-04-22 21:46", "2018-05-22 03:49", "2018-06-20 10:51", "2018-07-19 19:52", "2018-08-18 07:49", "2018-09-16 23:15", "2018-10-16 18:02", "2018-11-15 14:54", "2018-12-15 11:49")
        self.lastQuarterArray = ("2008-01-30 05:03", "2008-02-29 02:18", "2008-03-29 21:47", "2008-04-28 14:12", "2008-05-28 02:57", "2008-06-26 12:10", "2008-07-25 18:42", "2008-08-23 23:50", "2008-09-22 05:04", "2008-10-21 11:55", "2008-11-19 21:31", "2008-12-19 10:29", "2009-01-18 02:46", "2009-02-16 21:37", "2009-03-18 17:47", "2009-04-17 13:36", "2009-05-17 07:26", "2009-06-15 22:15", "2009-07-15 09:53", "2009-08-13 18:55", "2009-09-12 02:16", "2009-10-11 08:56", "2009-11-09 15:56", "2009-12-09 00:13", "2010-01-07 10:40", "2010-02-05 23:49", "2010-03-07 15:42", "2010-04-06 09:37", "2010-05-06 04:15", "2010-06-04 22:13", "2010-07-04 14:35", "2010-08-03 04:59", "2010-09-01 17:22", "2010-10-01 03:52", "2010-10-30 12:46", "2010-11-28 20:36", "2010-12-28 04:18", "2011-01-26 12:57", "2011-02-24 23:26", "2011-03-26 12:07", "2011-04-25 02:47", "2011-05-24 18:52", "2011-06-23 11:48", "2011-07-23 05:02", "2011-08-21 21:55", "2011-09-20 13:39", "2011-10-20 03:30", "2011-11-18 15:09", "2011-12-18 00:48", "2012-01-16 09:08", "2012-02-14 17:04", "2012-03-15 01:25", "2012-04-13 10:50", "2012-05-12 21:47", "2012-06-11 10:41", "2012-07-11 01:48", "2012-08-09 18:55", "2012-09-08 13:15", "2012-10-08 07:33", "2012-11-07 00:36", "2012-12-06 15:32", "2013-01-05 03:58", "2013-02-03 13:56", "2013-03-04 21:53", "2013-04-03 04:37", "2013-05-02 11:14", "2013-05-31 18:58", "2013-06-30 04:54", "2013-07-29 17:43", "2013-08-28 09:35", "2013-09-27 03:56", "2013-10-26 23:41", "2013-11-25 19:28", "2013-12-25 13:48", "2014-01-24 05:19", "2014-02-22 17:15", "2014-03-24 01:46", "2014-04-22 07:52", "2014-05-21 12:59", "2014-06-19 18:39", "2014-07-19 02:08", "2014-08-17 12:26", "2014-09-16 02:05", "2014-10-15 19:12", "2014-11-14 15:16", "2014-12-14 12:51", "2015-01-13 09:47", "2015-02-12 03:50", "2015-03-13 17:48", "2015-04-12 03:44", "2015-05-11 10:36", "2015-06-09 15:42", "2015-07-08 20:24", "2015-08-07 02:03", "2015-09-05 09:54", "2015-10-04 21:06", "2015-11-03 12:24", "2015-12-03 07:40", "2016-01-02 05:30", "2016-02-01 03:28", "2016-03-01 23:11", "2016-03-31 15:17", "2016-04-30 03:29", "2016-05-29 12:12", "2016-06-27 18:19", "2016-07-26 23:00", "2016-08-25 03:41", "2016-09-23 09:56", "2016-10-22 19:14", "2016-11-21 08:33", "2016-12-21 01:56", "2017-01-19 22:14", "2017-02-18 19:33", "2017-03-20 15:58", "2017-04-19 09:57", "2017-05-19 00:33", "2017-06-17 11:33", "2017-07-16 19:26", "2017-08-15 01:15", "2017-09-13 06:25", "2017-10-12 12:25", "2017-11-10 20:37", "2017-12-10 07:51", "2018-01-08 22:25", "2018-02-07 15:54", "2018-03-09 11:20", "2018-04-08 07:18", "2018-05-08 02:09", "2018-06-06 18:32", "2018-07-06 07:51", "2018-08-04 18:18", "2018-09-03 02:37", "2018-10-02 09:45", "2018-10-31 16:40", "2018-11-30 00:19", "2018-12-29 09:34")

    def update_moon_calculations(self, theDate):
        """Generate all Moon data ready for display."""
        SECONDS_PER_DAY = 86400.0
        lastNewMoonSeconds = self.last_new_moon_seconds_at_time(theDate)
        nextNewMoonSeconds = self.next_new_moon_seconds_at_time(theDate)
        lastFullMoonSeconds = self.last_full_moon_seconds_at_time(theDate)
        nextFullMoonSeconds = self.next_full_moon_seconds_at_time(theDate)
        lastQuarterMoonSeconds = self.last_quarter_moon_seconds_at_time(theDate)
        nextQuarterMoonSeconds = self.next_quarter_moon_seconds_at_time(theDate)

        # Calculate phase percent of Moon based on nearest two data values
        if nextFullMoonSeconds <= nextNewMoonSeconds:
            if nextQuarterMoonSeconds <= nextFullMoonSeconds:
                self.phaseOfMoon = (lastNewMoonSeconds / (lastNewMoonSeconds + nextQuarterMoonSeconds)) * 0.25
            else:
                self.phaseOfMoon = (lastQuarterMoonSeconds / (lastQuarterMoonSeconds + nextFullMoonSeconds)) * 0.25 + 0.25
        else:
            if nextQuarterMoonSeconds <= nextNewMoonSeconds:
                self.phaseOfMoon = (lastFullMoonSeconds / (lastFullMoonSeconds + nextQuarterMoonSeconds)) * 0.25 + 0.5
            else:
                self.phaseOfMoon = (lastQuarterMoonSeconds / (lastQuarterMoonSeconds + nextNewMoonSeconds)) * 0.25 + 0.75

        # Generate interesting human readable values
        self.percentOfFullMoon = (math.cos(((self.phaseOfMoon + .5) / .5 * math.pi)) + 1) * .5
        self.julianDate = 2452135 + ((theDate - 997700400.0) / SECONDS_PER_DAY)
        self.lunation = self.lunation_at_time(theDate)
        dayWithFraction = lastNewMoonSeconds / SECONDS_PER_DAY
        self.daysOld = math.floor(dayWithFraction)
        self.hoursOld = math.floor((dayWithFraction - self.daysOld) * 24)
        self.minutesOld = math.floor((((dayWithFraction - self.daysOld) * 24) - self.hoursOld) * 60)
        self.daysUntilNewMoon = nextNewMoonSeconds / SECONDS_PER_DAY
        self.nextNewMoonDate = theDate + nextNewMoonSeconds - self.correct_for_tz_and_dst(theDate + nextNewMoonSeconds)
        self.daysUntilFullMoon = nextFullMoonSeconds / SECONDS_PER_DAY
        self.nextFullMoonDate = theDate + nextFullMoonSeconds - self.correct_for_tz_and_dst(theDate + nextFullMoonSeconds)
        
        # Eclipse information
        self.nextLunarEclipseSeconds = self.next_lunar_eclipse_seconds_at_time(theDate)
        self.nextSolarEclipseSeconds = self.next_solar_eclipse_seconds_at_time(theDate)
        self.lastLunarEclipseSeconds = self.last_lunar_eclipse_seconds_at_time(theDate)
        self.daysUntilLunarEclipse = self.nextLunarEclipseSeconds / SECONDS_PER_DAY
        self.nextLunarEclipseDate = theDate + self.nextLunarEclipseSeconds - self.correct_for_tz_and_dst(theDate + self.nextLunarEclipseSeconds)
        self.daysUntilSolarEclipse = self.nextSolarEclipseSeconds / SECONDS_PER_DAY
        self.nextSolarEclipseDate = theDate + self.nextSolarEclipseSeconds - self.correct_for_tz_and_dst(theDate + self.nextSolarEclipseSeconds)

        # Selenographic terminator longitude
        selenographicTmp = 270 + (self.phaseOfMoon * 360)
        if selenographicTmp >= 360:
            selenographicTmp -= 360
        if selenographicTmp >= 270:
            selenographicTmp -= 360
        elif selenographicTmp >= 180:
            selenographicTmp -= 180
        elif selenographicTmp >= 90:
            selenographicTmp -= 180
        selenographicTmp = -selenographicTmp
        if selenographicTmp < 0:
            self.westOrEast = _("west")
        else:
            self.westOrEast = _("east")
        self.selenographicDeg = abs(selenographicTmp)
        if self.phaseOfMoon >= .5:
            self.riseOrSet = _("Sunset")
        else:
            self.riseOrSet = _("Sunrise")
            
    def correct_for_tz_and_dst(self, dateSecOfEvent):
        """Time-zone and/or daylight-saving correction for a displayed event (internal data all UTC)."""
        if time.daylight == 0 or time.localtime(dateSecOfEvent)[8] == 0:
            # Time-zone correction
            return time.timezone
        else:
            # Time-zone & daylight saving correction
            return time.altzone

    def moon_phase_name(self, phaseOfMoon):
        """Return the moon image name for a given phase value."""
        if phaseOfMoon >= 0 and phaseOfMoon < 0.025:
            return _("New Moon")
        elif phaseOfMoon >= 0.025 and phaseOfMoon < 0.225:
            return _("Waxing Crescent")
        elif phaseOfMoon >= 0.225 and phaseOfMoon < 0.275:
            return _("First Quarter")
        elif phaseOfMoon >= 0.275 and phaseOfMoon < 0.475:
            return _("Waxing Gibbous")
        elif phaseOfMoon >= 0.475 and phaseOfMoon < 0.525:
            return _("Full Moon")
        elif phaseOfMoon >= 0.525 and phaseOfMoon < 0.735:
            return _("Waning Gibbous")
        elif phaseOfMoon >= 0.735 and phaseOfMoon < 0.775:
            return _("Last Quarter")
        elif phaseOfMoon >= 0.775 and phaseOfMoon < 0.975:
            return _("Waning Crescent")
        else:
            return _("New Moon")

    def next_full_moon_seconds_at_time(self, now):
        """Return seconds to the next Full Moon."""
        for dateString in self.fullMoonArray:
            next = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
            if next >= now:
                break
        return next - now

    def next_new_moon_seconds_at_time(self, now):
        """Return seconds to the next New Moon."""
        for dateString in self.newMoonArray:
            next = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
            if next >= now:
                break
        return next - now

    def next_quarter_moon_seconds_at_time(self, now):
        """Return seconds to the next Quater Moon phase (could be First or Last)."""
        for dateString in self.firstQuarterArray:
            next1 = time.mktime(time.strptime(dateString, self.dateFormat))
            if next1 >= now:
                break
        for dateString in self.lastQuarterArray:
            next2 = time.mktime(time.strptime(dateString, self.dateFormat))
            if next2 >= now:
                break
        next = min(next1, next2)
        return next - now

    def last_full_moon_seconds_at_time(self, now):
        """Return (positive) seconds since the last Full Moon."""
        for dateString in self.fullMoonArray:
            then = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
            if then >= now:
                break
            last = then
        return now - last

    def last_new_moon_seconds_at_time(self, now):
        """Return (positive) seconds since the last New Moon."""
        for dateString in self.newMoonArray:
            then = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
            if then >= now:
                break
            last = then
        return now - last

    def last_quarter_moon_seconds_at_time(self, now):
        """Return (positive) seconds to the last Quater Moon phase (could be First or Last)."""
        for dateString in self.firstQuarterArray:
            then = time.mktime(time.strptime(dateString, self.dateFormat))
            if then >= now:
                break
            last1 = then
        for dateString in self.lastQuarterArray:
            then = time.mktime(time.strptime(dateString, self.dateFormat))
            if then >= now:
                break
            last2 = then
        last = max(last1, last2)
        return now - last

    def lunation_at_time(self, now):
        """Return lunation number, 0 started on Dec 18, 1922, current data set starts as 2008"""
        lunation = 1051
        for dateString in self.newMoonArray:
            next = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
            if next >= now:
                break
            lunation += 1
        return lunation

    def next_lunar_eclipse_seconds_at_time(self, now):
        """Return (positive) seconds to the next Lunar eclipe or -1."""
        for dateString in self.fullMoonArray:
            if dateString[-1:] != "_":
                next = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
                if next >= now:
                    return next - now
        return -1

    def last_lunar_eclipse_seconds_at_time(self, now):
        """Return (positive) seconds to the last Lunar eclipe or -1."""
        last = -1
        for dateString in self.fullMoonArray:
            if dateString[-1:] != "_":
                then = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
                if then >= now:
                    break
                last = then
        if last == -1:
            return -1
        else:
            return now - last

    def next_solar_eclipse_seconds_at_time(self, now):
        """Return (positive) seconds to the next Solar eclipe or -1."""
        for dateString in self.newMoonArray:
            if dateString[-1:] != "_":
                next = time.mktime(time.strptime(dateString[:-1], self.dateFormat))
                if next >= now:
                    return next - now
        return -1
