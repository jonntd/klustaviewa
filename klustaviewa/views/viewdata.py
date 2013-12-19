"""Get the keyword arguments for the views from the loader."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------
import numpy as np
import pandas as pd

from qtools import inthread, inprocess
from qtools import QtGui, QtCore

from spikedetekt2.dataio import *
import kwiklib.utils.logger as log
from kwiklib.dataio import (get_some_spikes_in_clusters, get_indices, 
    get_spikes_in_clusters, get_some_spikes)
from kwiklib.utils.colors import random_color

from klustaviewa.stats.correlations import normalize
from klustaviewa.stats.correlograms import get_baselines, NCORRBINS_DEFAULT, CORRBIN_DEFAULT
from klustaviewa import USERPREF
from klustaviewa import SETTINGS
from klustaviewa.gui.threads import ThreadedTasks


# -----------------------------------------------------------------------------
# Get data from loader for views
# -----------------------------------------------------------------------------
def get_waveformview_data(exp, clusters=[], channel_group=0, clustering='main',
                          autozoom=None, wizard=None):
    # TODO: add spikes=None keyword
    # TODO: add normalization coefficient in keyword argument
    fetdim = exp.application_data.spikedetekt.nfeatures_per_channel
    
    clusters_data = getattr(exp.channel_groups[channel_group].clusters, clustering)
    spikes_data = exp.channel_groups[channel_group].spikes
    channels_data = exp.channel_groups[channel_group].channels
    
    spike_clusters = getattr(spikes_data.clusters, clustering)[:]
    spikes_selected = get_some_spikes_in_clusters(clusters, spike_clusters)
    cluster_colors = np.array([clusters_data[cl].application_data.klustaviewa.color or 1
                               for cl in clusters])

    waveforms = spikes_data.waveforms_filtered[spikes_selected,...]
    masks = spikes_data.masks[spikes_selected,::fetdim]
    
    # Normalize waveforms.
    waveforms = waveforms * 1. / (waveforms.max())
    
    channel_positions = np.array([channels_data[ch].position or (0., ch) 
                                  for ch in channels_data.keys()])
    
    # TODO: pandaize
    
    data = dict(
        waveforms=waveforms,
        clusters=spike_clusters,
        cluster_colors=cluster_colors,
        clusters_selected=clusters,
        masks=masks,
        geometrical_positions=channel_positions,
        autozoom=autozoom,
        keep_order=wizard,
    )
    return data

def get_traceview_data(loader):
    return loader.get_trace()
    
def get_clusterview_data(loader, statscache, clusters=None):
    data = dict(
        cluster_colors=loader.get_cluster_colors('all',
            can_override=False),
        cluster_groups=loader.get_cluster_groups('all'),
        group_colors=loader.get_group_colors('all'),
        group_names=loader.get_group_names('all'),
        cluster_sizes=loader.get_cluster_sizes('all'),
        cluster_quality=statscache.cluster_quality,
    )
    return data
    
def get_channelview_data(loader, channels=None):
    data = dict(
        channel_colors=loader.get_channel_colors('all',
            can_override=False),
        channel_groups=loader.get_channel_groups('all'),
        channel_names=loader.get_channel_names('all'),
        group_colors=loader.get_channel_group_colors('all'),
        group_names=loader.get_channel_group_names('all'),
    )
    return data
    
def get_correlogramsview_data(loader, statscache):
    clusters_selected0 = loader.get_clusters_selected()
    
    # Subset of selected clusters if there are too many clusters.
    max_nclusters = USERPREF['correlograms_max_nclusters']
    if len(clusters_selected0) < max_nclusters:
        clusters_selected = clusters_selected0
    else:
        clusters_selected = clusters_selected0[:max_nclusters]
    
    correlograms = statscache.correlograms.submatrix(
        clusters_selected)
    # Compute the baselines.
    sizes = get_array(select(loader.get_cluster_sizes(), clusters_selected))
    colors = select(loader.get_cluster_colors(), clusters_selected)
    corrbin = SETTINGS.get('correlograms.corrbin', CORRBIN_DEFAULT)
    ncorrbins = SETTINGS.get('correlograms.ncorrbins', NCORRBINS_DEFAULT)
    duration = corrbin * ncorrbins
    baselines = get_baselines(sizes, duration, corrbin)
    data = dict(
        correlograms=correlograms,
        baselines=baselines,
        clusters_selected=clusters_selected,
        cluster_colors=colors,
        ncorrbins=ncorrbins,
        corrbin=corrbin,
    )
    return data
    
def get_similaritymatrixview_data(loader, statscache):
    if statscache is None:
        return
    similarity_matrix = statscache.similarity_matrix_normalized
    # Clusters in groups 0 or 1 to hide.
    cluster_groups = loader.get_cluster_groups('all')
    clusters_hidden = np.nonzero(np.in1d(cluster_groups, [0, 1]))[0]
    data = dict(
        # WARNING: copy the matrix here so that we don't modify the
        # original matrix while normalizing it.
        similarity_matrix=similarity_matrix,
        cluster_colors_full=loader.get_cluster_colors('all'),
        clusters_hidden=clusters_hidden,
    )
    return data
    
def get_featureview_data(exp, clusters=[], channel_group=0, clustering='main',
                         nspikes_bg=None, autozoom=None):
    # TODO: add spikes=None and spikes_bg=None
    # TODO: add normalization coefficient in keyword argument
    fetdim = exp.application_data.spikedetekt.nfeatures_per_channel
    
    clusters_data = getattr(exp.channel_groups[channel_group].clusters, clustering)
    spikes_data = exp.channel_groups[channel_group].spikes
    channels_data = exp.channel_groups[channel_group].channels
    
    spike_clusters = getattr(spikes_data.clusters, clustering)[:]
    spikes_selected = get_spikes_in_clusters(clusters, spike_clusters)
    spikes_bg = get_some_spikes(spike_clusters, nspikes_max=nspikes_bg)
    cluster_colors = np.array([clusters_data[cl].application_data.klustaviewa.color or 1
                               for cl in clusters])
    
    # HACK: work-around PyTables bug #310: expand the dimensions of the boolean 
    # indices
    ind = np.tile(spikes_selected[:, np.newaxis, np.newaxis], 
                  (1,) + spikes_data.features_masks.shape[1:])
    fm = spikes_data.features_masks[ind].reshape((-1,) + spikes_data.features_masks.shape[1:])
    
    features = fm[:, :, 0]
    masks = fm[:, ::fetdim, 1]
    
    spiketimes = spikes_data.time_samples[spikes_selected]
    nchannels = features.shape[1]
    freq = exp.application_data.spikedetekt.sampling_frequency
    duration = exp.application_data.spikedetekt.duration
    
    # No need for hacky work-around here, since get_spikes returns a slice.
    features_bg = spikes_data.features_masks[spikes_bg, :, 0]
    
    # Normalize features.
    c = 1. / (features.max())
    features = features * c
    features_bg = features_bg * c
    
    # TODO: pandaize
    
    # TODO
    nextrafet = 0
    
    data = dict(
        features=features,
        features_background=features_bg,
        masks=masks,
        spiketimes=spiketimes,
        clusters=spike_clusters,
        clusters_selected=clusters,
        cluster_colors=cluster_colors,
        nchannels=nchannels,
        fetdim=fetdim,
        nextrafet=nextrafet,
        freq=freq,
        autozoom=autozoom,
        duration=duration,
        # TODO
        # alpha_selected=USERPREF.get('feature_selected_alpha', .75),
        # alpha_background=USERPREF.get('feature_background_alpha', .1),
        # time_unit=USERPREF['features_info_time_unit'] or 'second',
    )        
    return data