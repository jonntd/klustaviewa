"""Raw Data View: show raw data traces."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------
import numpy as np
import numpy.random as rdn
from numpy.lib.stride_tricks import as_strided
from collections import Counter
import operator
import time

from galry import (Manager, PlotPaintManager, EventProcessor, PlotInteractionManager, Visual,
    GalryWidget, QtGui, QtCore, show_window, enforce_dtype, NavigationEventProcessor, GridVisual, RectanglesVisual,
    TextVisual, DataNormalizer, process_coordinates, get_next_color, get_color)
from klustaviewa.views.common import KlustaViewaBindings, KlustaView
import klustaviewa.utils.logger as log
from klustaviewa.utils.settings import SETTINGS

__all__ = ['RawDataView']

# -----------------------------------------------------------------------------
# Data manager
# -----------------------------------------------------------------------------

class RawDataManager(Manager):
    info = {}
    def set_data(self, rawdata=None, freq=None):
        
        self.max_size = 500
        
        samples = rawdata[:5000, :]
        position, shape = process_coordinates(samples.T)
        xlim = 1., 20.
        
        self.shape = shape
        self.freq = freq
        self.duration = samples.shape[0]/self.freq
        
        xlimex, slice = self.get_view(shape[0], xlim, freq)
        samples, bounds, size = self.get_undersampled_data(rawdata, xlimex, slice) 
        
        self.rawdata = rawdata
        self.samples = samples
        self.position = position
        self.interaction_manager.get_processor('grid').update_viewbox()
        self.interaction_manager.activate_grid()
        print shape
    
    def get_view(self, total_size, xlim, freq): 
        """Return the slice of the data.

        Arguments:

          * xlim: (x0, x1) of the window currently displayed.

        """
        # Viewport.
        x0, x1 = xlim
        d = x1 - x0
        dmax = self.duration
        zoom = max(dmax / d, 1.)
        view_size = total_size / zoom
        step = int(np.ceil(view_size / self.max_size))
        # Extended viewport for data.
        x0ex = np.clip(x0 - 3 * d, 0, dmax)
        x1ex = np.clip(x1 + 3 * d, 0, dmax)
        i0 = np.clip(int(np.round(x0ex * freq)), 0, total_size)
        i1 = np.clip(int(np.round(x1ex * freq)), 0, total_size)
        return (x0ex, x1ex), slice(i0, i1, step)
            
    def get_undersampled_data(self, data, xlim, slice):
        duration_initial = 5
        """
        Arguments:
    
          * data: a HDF5 dataset of size Nsamples x Nchannels.
          * xlim: (x0, x1) of the current data view.
    
        """
        total_size = data.shape[0]
        # Get the view slice.
        # x0ex, x1ex = xlim
        # x0d, x1d = x0ex / (duration_initial) * 2 - 1, x1ex / (duration_initial) * 2 - 1
        # Extract the samples from the data (HDD access).
        samples = data[slice, :]
        # Convert the data into floating points.
        samples = np.array(samples, dtype=np.float32)
        # Normalize the data.
        samples *= (1. / 65535)
        # samples *= .25
        # Size of the slice.
        nsamples, nchannels = samples.shape
        # Create the data array for the plot visual.
        M = np.empty((nsamples * nchannels, 2))
        samples = samples.T# + np.linspace(-1., 1., nchannels).reshape((-1, 1))
        M[:, 1] = samples.ravel()
        # Generate the x coordinates.
        x = np.arange(slice.start, slice.stop, slice.step) / float(total_size - 1)
        # [0, 1] -> [-1, 2*duration.duration_initial - 1]
        x = x * 2 * self.duration / duration_initial - 1
        M[:, 0] = np.tile(x, nchannels)
        # Update the bounds.
        bounds = np.arange(nchannels + 1) * nsamples
        size = bounds[-1]
        return M, bounds, size
        
#    def update(self, data, xlimex, slice):
#        samples, bounds, size = get_undersampled_data(data, xlimex, slice)
#        nsamples = samples.shape[0]
#        color_array_index = np.repeat(np.arange(nchannels), nsamples / nchannels)
#        self.info = dict(position0=samples, bounds=bounds, size=size,
#            index=color_array_index)
            
# -----------------------------------------------------------------------------
# Visuals
# -----------------------------------------------------------------------------
class RawDataPaintManager(PlotPaintManager):
    def initialize(self):
        self.add_visual(MultiChannelVisual,
            position=self.data_manager.position,
            name='rawdata_waveforms',
            shape=self.data_manager.shape)
        
        self.add_visual(GridVisual, name='grid')

    def update(self):
        self.set_data(visual='rawdata_waveforms',
            position=self.data_manager.position)
            

class MultiChannelVisual(Visual):
    def initialize(self, color=None, point_size=1.0,
            position=None, shape=None, nprimitives=None, index=None,
            color_array_index=None, channel_height=0.25,
            options=None, autocolor=1):
        
        # register the size of the data
        self.size = np.prod(shape)
        
        # there is one plot per row
        if not nprimitives:
            nprimitives = shape[0]
            nsamples = shape[1]
        else:
            nsamples = self.size // nprimitives
        
        # register the bounds
        if nsamples <= 1:
            self.bounds = [0, self.size]
        else:
            self.bounds = np.arange(0, self.size + 1, nsamples)
        
        # automatic color with color map
        if autocolor is not None:
            if nprimitives <= 1:
                color = get_next_color(autocolor)
            else:
                color = np.array([get_next_color(i + autocolor) for i in xrange(nprimitives)])
            
        # set position attribute
        self.add_attribute("position0", ndim=2, data=position, autonormalizable=True)
        
        index = np.array(index)
        self.add_index("index", data=index)
    
        if color_array_index is None:
            color_array_index = np.repeat(np.arange(nprimitives), nsamples)
        color_array_index = np.array(color_array_index)
            
        ncolors = color.shape[0]
        ncomponents = color.shape[1]
        color = color.reshape((1, ncolors, ncomponents))
        
        dx = 1. / ncolors
        offset = dx / 2.
        
        self.add_texture('colormap', ncomponents=ncomponents, ndim=1, data=color)
        self.add_attribute('index', ndim=1, vartype='int', data=color_array_index)
        self.add_varying('vindex', vartype='int', ndim=1)
        self.add_uniform('nchannels', vartype='float', ndim=1, data=float(nprimitives))
        self.add_uniform('channel_height', vartype='float', ndim=1, data=channel_height)
        
        self.add_vertex_main("""
        vec2 position = position0;
        position.y = channel_height * position.y + .9 * (2 * index - (nchannels - 1)) / (nchannels - 1);
        vindex = index;
        """)
        
        self.add_fragment_main("""
        float coord = %.5f + vindex * %.5f;
        vec4 color = texture1D(colormap, coord);
        out_color = color;
        """ % (offset, dx))
        
        # add point size uniform (when it's not specified, there might be some
        # bugs where its value is obtained from other datasets...)
        self.add_uniform("point_size", data=point_size)
        self.add_vertex_main("""gl_PointSize = point_size;""")
        

# -----------------------------------------------------------------------------
# Grid
# -----------------------------------------------------------------------------
def nicenum(x, round=False):
    e = np.floor(np.log10(x))
    f = x / 10 ** e
    eps = 1e-6
    if round:
        if f < 1.5:
            nf = 1.
        elif f < 3:
            nf = 2.
        elif f < 7.:
            nf = 5.
        else:
            nf = 10.
    else:
        if f < 1 - eps:
            nf = 1.
        elif f < 2 - eps:
            nf = 2.
        elif f < 5 - eps:
            nf = 5.
        else:
            nf = 10.
    return nf * 10 ** e

def get_ticks(x0, x1):
    nticks = 5
    r = nicenum(x1 - x0, False)
    d = nicenum(r / (nticks - 1), True)
    g0 = np.floor(x0 / d) * d
    g1 = np.ceil(x1 / d) * d
    nfrac = int(max(-np.floor(np.log10(d)), 0))
    return np.arange(g0, g1 + .5 * d, d), nfrac

def format_number(x, nfrac=None):
    if nfrac is None:
        nfrac = 2

    if np.abs(x) < 1e-15:
        return "0"

    elif np.abs(x) > 100.001:
        return "%.3e" % x

    if nfrac <= 2:
        return "%.2f" % x
    else:
        nfrac = nfrac + int(np.log10(np.abs(x)))
        return ("%." + str(nfrac) + "e") % x

def get_ticks_text(x0, y0, x1, y1):
    ticksx, nfracx = get_ticks(x0, x1)
    ticksy, nfracy = get_ticks(y0, y1)
    n = len(ticksx)
    text = [format_number(x, nfracx) for x in ticksx]
    text += [format_number(x, nfracy) for x in ticksy]
    # position of the ticks
    coordinates = np.zeros((len(text), 2))
    coordinates[:n, 0] = ticksx
    coordinates[n:, 1] = ticksy
    return text, coordinates, n

class GridEventProcessor(EventProcessor):
    def initialize(self):
        self.register('Initialize', self.update_axes)
        self.register('Pan', self.update_axes)
        self.register('Zoom', self.update_axes)
        self.register('Reset', self.update_axes)
        self.register('Animate', self.update_axes)
        self.register(None, self.update_axes)
        
    def update_viewbox(self):
        # normalization viewbox
        self.normalizer = DataNormalizer()
        self.normalizer.normalize(
            (0, -1, self.parent.data_manager.duration, 1))

    def update_axes(self, parameter):
        nav = self.get_processor('navigation')
        if not nav:
            return

        viewbox = nav.get_viewbox()

        x0, y0, x1, y1 = viewbox
        x0 = self.normalizer.unnormalize_x(x0)
        y0 = self.normalizer.unnormalize_y(y0)
        x1 = self.normalizer.unnormalize_x(x1)
        y1 = self.normalizer.unnormalize_y(y1)
        viewbox = (x0, y0, x1, y1)

        text, coordinates, n = get_ticks_text(*viewbox)

        coordinates[:,0] = self.normalizer.normalize_x(coordinates[:,0])
        coordinates[:,1] = self.normalizer.normalize_y(coordinates[:,1])

        # here: coordinates contains positions centered on the static
        # xy=0 axes of the screen
        position = np.repeat(coordinates, 2, axis=0)
        position[:2 * n:2,1] = -1
        position[1:2 * n:2,1] = 1
        position[2 * n::2,0] = -1
        position[2 * n + 1::2,0] = 1

        axis = np.zeros(len(position))
        axis[2 * n:] = 1

        self.set_data(visual='grid_lines', position=position, axis=axis)

        coordinates[n:, 0] = -.95
        coordinates[:n, 1] = -.95

        t = "".join(text)
        n1 = len("".join(text[:n]))
        n2 = len("".join(text[n:]))

        axis = np.zeros(n1+n2)
        axis[n1:] = 1

        self.set_data(visual='grid_text', text=text,
            coordinates=coordinates,
            axis=axis)

# -----------------------------------------------------------------------------
# Interactivity
# -----------------------------------------------------------------------------
class RawDataInteractionManager(PlotInteractionManager):
    def initialize_default(self, constrain_navigation=None,
        momentum=True,
        ):
        
        super(PlotInteractionManager, self).initialize_default()
        self.add_processor(NavigationEventProcessor,
            constrain_navigation=constrain_navigation, 
            momentum=momentum,
            name='navigation')
        self.add_processor(GridEventProcessor, name='grid')
        
    def activate_grid(self):
        self.paint_manager.set_data(visual='grid_lines', 
            visible=True)
        processor = self.get_processor('grid')
        if processor:
            processor.activate(True)
            processor.update_axes(None)
    
class RawDataBindings(KlustaViewaBindings):
    pass

# -----------------------------------------------------------------------------
# Top-level widget
# -----------------------------------------------------------------------------
class RawDataView(KlustaView):
    
    # Initialization
    # --------------
    def initialize(self):
        
        self.set_bindings(RawDataBindings)
        self.set_companion_classes(
            paint_manager=RawDataPaintManager,
            interaction_manager=RawDataInteractionManager,
            data_manager=RawDataManager)
    
    def set_data(self, *args, **kwargs):
        self.data_manager.set_data(*args, **kwargs)

        # update?
        if self.initialized:
            self.paint_manager.update()
            self.updateGL()
      
        