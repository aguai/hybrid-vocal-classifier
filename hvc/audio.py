import numpy as np
from scipy.io import wavfile
from scipy.signal import slepian # AKA DPSS, window used for FFT
from scipy.signal import spectrogram

from hvc.evfuncs import load_cbin,load_notmat

class song_spect:
    """
    spectrogram object, returned by make_spect.
    Properties:
        spect -- 2-d m by n numpy array, spectrogram as computed by make_song_spect.
                 Each of the m rows is a frequency bin, and each of the n columns is a time bin.
        time_bins -- 1d vector, values are times represented by each bin in s
        freq_bins -- 1d vector, values are power spectral density in each frequency bin
        sampfreq -- sampling frequency in Hz as determined by scipy.io.wavfile function
    """
    def __init__(self,spect,freq_bins,time_bins,sampfreq):
        self.spect = spect
        self.freqBins = freq_bins
        self.timeBins = time_bins
        self.sampFreq = sampfreq

def make_spect(waveform,sampfreq,size=512,step=32,freq_cutoffs=[1000,8000]):
    """
    Computes spectogram of raw song waveform using FFT.
    Defaults to FFT parameters from Koumura Okanoya 2016.
    **Note that spectrogram is log transformed (base 10), and that
    both spectrogram and freq_bins are "flipped" (reflected across horizontal
    axis) so that when plotted the lower frequencies of the spectrogram are 
    at 0 on the y axis.

    Inputs:
        wav_file -- filename of .wav file corresponding to song
        size -- of FFT window, default is 512 samples
        step -- number of samples between the start of each window, default is 32
            i.e. if size == step then there will be no overlap of windows
        freq_range -- range of frequencies to return. Two-element list; frequencies
                      less than the first element or greater than the second are discarded.
    Returns:
        spect -- spectrogram, log transformed
        time_bins -- vector assigning time values to each column in spect
            e.g. [0,8,16] <-- 8 ms time bins
        freq_bins -- vector assigning frequency values to each row in spect
            e.g. [0,100,200] <-- 100 Hz frequency bins
    """
    win_dpss = slepian(size, 4/size)
    fft_overlap = size - step
    freq_bins, time_bins, spect = spectrogram(waveform,
                           sampfreq,
                           window=win_dpss,
                           nperseg=win_dpss.shape[0],
                           noverlap=fft_overlap)
    #below, I set freq_bins to >= freq_cutoffs 
    #so that Koumura default of [1000,8000] returns 112 freq. bins
    f_inds = np.nonzero((freq_bins >= freq_cutoffs[0]) & 
                        (freq_bins < freq_cutoffs[1]))[0] #returns tuple
    freq_bins = freq_bins[f_inds]
    spect = spect[f_inds,:]
    spect = np.log10(spect) # log transform to increase range

    #flip spect and freq_bins so lowest frequency is at 0 on y axis when plotted
    spect = np.flipud(spect)
    freq_bins = np.flipud(freq_bins)
    spect_obj = song_spect(spect,freq_bins,time_bins,sampfreq)
    return spect_obj
    
def compute_amp(spect):
    """
    compute amplitude of spectrogram
    Assumes the values for frequencies are power spectral density (PSD).
    Sums PSD for each time bin, i.e. in each column.
    Inputs:
        spect -- output from spect_from_song
    Returns:
        amp -- amplitude
    """

    return np.sum(spect,axis=0)

def segment_song(amp,time_bins,threshold=5000,min_syl_dur=0.02,min_silent_dur=0.002):
    """
    Divides songs into segments based on threshold crossings of amplitude.
    Returns onsets and offsets of segments, corresponding (hopefully) to syllables in a song.
    Inputs:
        amp -- amplitude of power spectral density. Returned by compute_amp.
        time_bins -- time in s, must be same length as log amp. Returned by make_song_spect.
        threshold -- value above which amplitude is considered part of a segment. default is 5000.
        min_syl_dur -- minimum duration of a syllable. default is 0.02, i.e. 20 ms.
        min_silent_dur -- minimum duration of silent gap between syllables. default is 0.002, i.e. 2 ms.
    Returns:
        onsets, offsets -- arrays of onsets and offsets of segments.
        So for syllable 1 of a song, its onset is onsets[0] and its offset is offsets[0].
        To get that segment of the spectrogram, you'd take spect[:,onsets[0]:offsets[0]]
    """
    above_th = amp > threshold
    h = [1, -1] 
    above_th_convoluted = np.convolve(h,above_th) # convolving with h causes:
    # +1 whenever above_th changes from 0 to 1
    onsets = time_bins[np.nonzero(above_th_convoluted > 0)]
    # and -1 whenever above_th changes from 1 to 0
    offsets = time_bins[np.nonzero(above_th_convoluted < 0)]
    
    #get rid of silent intervals that are shorter than min_silent_dur
    silent_gap_durs = onsets[1:] - offsets[:-1] # duration of silent gaps
    keep_these = np.nonzero(silent_gap_durs > min_silent_dur)
    onsets = onsets[keep_these]
    offsets = offsets[keep_these]
    
    #eliminate syllables with duration shorter than min_syl_dur
    syl_durs = offsets - onsets
    keep_these = np.nonzero(syl_durs > min_syl_dur)
    onsets = onsets[keep_these]
    offsets = offsets[keep_these]    
    
    return onsets,offsets

def extract_syls(cbin,spect_params,labels_to_use='all',syl_spect_width=300):
    """
    extract syllables from song files using threshold crossings, then return
    spectrograms of each syllable along with associated label if there
    are labels
    
    Parameters
    ----------
    cbin : string
        .cbin filename
    spect_params: dictionary
        with keys 'window_size','window_step','freq_cutoffs', and 'samp_freq'.
        Note that 'samp_freq' is the **expected** sampling frequency and the
        function throws an error if the actual sampling frequency of cbin does
        not match the expected one.
    label_to_use : string
        String of all labels for which associated spectrogram should be made.
        E.g., if labels_to_use = 'iab' then syllables labeled 'i','a',or 'b'
        will be extracted and returned, but a syllable labeled 'x' would be
        ignored. If labels_to_use=='all' then all spectrograms are returned with
        empty strings for the labels. Default is 'all'.
    syl_spect_width : int
        total duration of each spectrogram, given in number of time bins in
        spectrogram. Default is 300 (assumes a time bin ~ 1 ms).

    Returns
    -------
    all_syl_spects : list of 2-d numpy arrays
        spectrogram
    all_syl_labels : list of chars
    """

    if labels_to_use != 'all':
        if type(labels_to_use) == str:
            labels_to_use = list(labels_to_use)
        else:
            ValueError('labels_to_use argument should be a string')

    all_syl_labels = []
    all_syl_spects = []
    dat, fs = load_cbin(cbin)
    if fs != spect_params['samp_freq']:
        raise ValueError(
            'Sampling frequency for {}, {}, does not match expected sampling '
            'frequency of {}'.format(cbin,
                                     fs,
                                     spect_params['samp_freq']))
    dat,fs = load_cbin(cbin)
    spect_obj = make_spect(dat,fs,size=spect_params['window_size'],
                           step=spect_params['window_step'],
                           freq_cutoffs=spect_params['freq_cutoffs'])
    spect = spect_obj.spect
    time_bins = spect_obj.timeBins

    notmat = load_notmat(cbin)
    labels = notmat['labels']
    onsets = notmat['onsets'] / 1000.0
    offsets = notmat['offsets'] / 1000.0
    onsets_time_bins = [np.argmin(np.abs(time_bins - onset))
                                for onset in onsets]
    offsets_time_bins = [np.argmin(np.abs(time_bins - offset))
                                for offset in offsets]
    #extract each syllable, but include the "silence" around it
    for ind,label in enumerate(labels):
        if labels_to_use == 'all':
            label = None
        elif label not in labels_to_use:
            continue
        temp_syl_spect = spect[:,onsets_time_bins[ind]:offsets_time_bins[ind]]
        width_diff = syl_spect_width - temp_syl_spect.shape[1]
        # take half of difference between spects and make that the start index
        # so one half of 'empty' area will be on one side of spect
        # and the other half will be on other side
        # i.e., center the spectrogram
        left_width = int(round(width_diff / 2))
        right_width = width_diff - left_width
        if left_width > onsets_time_bins[ind]:
            left_width = onsets_time_bins[ind]
            right_width = width_diff - left_width
        elif offsets_time_bins[ind] + right_width > spect.shape[-1]:
            right_width = spect.shape[-1] - offsets_time_bins[ind]
            left_width = width_diff - right_width
        temp_syl_spect = spect[:,onsets_time_bins[ind]-left_width:
                                 offsets_time_bins[ind]+right_width]
        all_syl_labels.append(label)
        all_syl_spects.append(temp_syl_spect)
    
    return all_syl_spects,all_syl_labels