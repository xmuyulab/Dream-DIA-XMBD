import sys
import os.path
import bisect
import numpy as np
import pandas as pd
from pyteomics import mzxml, mzml
from sklearn.metrics.pairwise import cosine_similarity

def load_library(library_file):
    """Read spectral library. Only .tsv and .csv formats are supported."""
    if library_file.endswith(".tsv"):
        library = pd.read_csv(library_file, "\t")
    elif library_file.endswith(".csv"):
        library = pd.read_csv(library_file)
    else:
        raise Exception("Invalid spectral library format: %s. Only .tsv and .csv formats are supported." % library_file)

    # Load column names
    lib_cols = {}
    f = open(os.path.join(os.path.dirname(sys.argv[0]), "lib_col_settings.txt"))
    for line in f:
        record = line.strip()
        if record and not record.startswith("#"):
            key, value = record.split("=")
            key = key.strip()
            value = value.strip()
            lib_cols[key] = value
    f.close()

    # Check column names
    necessary_columns = list(lib_cols.values())
    real_columns = list(library.columns)
    no_columns = [i for i in necessary_columns if i not in real_columns]
    if no_columns:
        raise Exception("Cannot find column(s) '%s' in the spectral library." % ";".join(no_columns))
    lib_cols["DECOY_OR_NOT_COL"] = "decoy"

    return lib_cols, library

def check_full_sequence(library, id_column, full_seq_column):
    abnormal_records = []
    for pep_id, full_seq in zip(library[id_column], library[full_seq_column]):
        if not pep_id.startswith("DECOY"):
            if pep_id.strip().split("_")[1] != full_seq:
                abnormal_records.append(pep_id)
    return abnormal_records

def correct_full_sequence(library, id_column, full_seq_column):
    abnormal_records = check_full_sequence(library, id_column, full_seq_column)
    abnormal_library = library[library[id_column].isin(abnormal_records)]
    abnormal_library[full_seq_column] = abnormal_library[id_column].apply(lambda x : x.strip().split("_")[1])
    new_library = library[~library[id_column].isin(abnormal_records)]
    new_library = pd.concat([new_library, abnormal_library], ignore_index = True)
    return new_library

def flatten_list(alist):
    flattened_list = []
    for elem in alist:
        flattened_list.extend(elem)
    return flattened_list

def endoIRT_generator(lib_cols, library, n_irt):
    target_library = library[library[lib_cols["DECOY_OR_NOT_COL"]] == 0]
    topN_peps = list(target_library.loc[:, [lib_cols["PRECURSOR_ID_COL"], lib_cols["LIB_INTENSITY_COL"]]].groupby(lib_cols["PRECURSOR_ID_COL"]).mean().sort_values(by = lib_cols["LIB_INTENSITY_COL"], ascending = False).index)[:n_irt]
    irt_library = target_library[target_library[lib_cols["PRECURSOR_ID_COL"]].isin(topN_peps)]
    return irt_library

def get_precursor_indice(precursor_ids):
    precursor_indice = []

    last_record = ""
    prec_index = [0]
    for i, prec in enumerate(precursor_ids):
        if last_record != prec:
            if i:
                precursor_indice.append(prec_index)
                prec_index = [i]
        else:
            prec_index.append(i)
        last_record = prec
    precursor_indice.append(prec_index)
    return precursor_indice

def tear_library(library, lib_cols, n_threads): 
    precursor_indice = get_precursor_indice(library[lib_cols["PRECURSOR_ID_COL"]])
    n_precursors = len(precursor_indice)
    n_each_chunk = n_precursors // n_threads
    chunk_indice = [[k + i * n_each_chunk for k in range(n_each_chunk)] for i in range(n_threads)]
    for i, idx in enumerate(range(chunk_indice[-1][-1] + 1, n_precursors)):
        chunk_indice[i].append(idx)
    
    return precursor_indice, chunk_indice

class MS1_Chrom:
    def __init__(self):      
        self.rt_list = []
        self.spectra = []

class MS2_Chrom:
    def __init__(self, win_id, win_min, win_max):
        self.win_id = win_id
        self.win_min = win_min
        self.win_max = win_max
        
        self.rt_list = []
        self.spectra = []

def filter_spectrum(spectrum, mz_min, mz_max):
    intensity_array = spectrum['intensity array']
    mz_array  = spectrum['m/z array'][intensity_array > 0]
    intensity_array = intensity_array[intensity_array > 0]

    ms_range = (mz_array >= mz_min) & (mz_array < mz_max)
    mz_array  = mz_array[ms_range]
    intensity_array = intensity_array[ms_range]

    return mz_array, intensity_array

def calc_win_id(precursor_mz, win_range):
    return bisect.bisect(win_range[:,0], precursor_mz) - 1

def load_rawdata(rawdata_file, win_file, mz_min, mz_max):
    if rawdata_file.endswith(".mzXML"):
        filetype = "mzxml"
    elif rawdata_file.endswith(".mzML"):
        filetype = "mzml"
    else:
        raise Exception("Invalid rawdata file: %s !\nOnly mzXML and mzML files are supported!" % rawdata_file)    
    
    if filetype == "mzxml":
        rawdata_reader = mzxml.MzXML(rawdata_file)
    else:
        rawdata_reader = mzml.MzML(rawdata_file)

    if filetype == "mzxml":
        mslevel_string = "msLevel"
        def get_RT_from_rawdata_spectrum(spectrum):
            return spectrum["retentionTime"]
        def get_precursor_mz_from_rawdata_spectrum(spectrum):
            return spectrum['precursorMz'][0]['precursorMz']
    else:
        mslevel_string = "ms level"
        def get_RT_from_rawdata_spectrum(spectrum):
            return spectrum["scanList"]["scan"][0]["scan start time"]
        def get_precursor_mz_from_rawdata_spectrum(spectrum):
            return spectrum["precursorList"]["precursor"][0]["selectedIonList"]["selectedIon"][0]['selected ion m/z']

    win_range = np.loadtxt(win_file)

    ms1 = MS1_Chrom()
    ms2 = [MS2_Chrom(i, each_win[0], each_win[1]) for i, each_win in enumerate(win_range)]

    for idx, spectrum in enumerate(rawdata_reader):
        if spectrum[mslevel_string] == 1:
            RT = 60 * get_RT_from_rawdata_spectrum(spectrum)
            mz_array, intensity_array = filter_spectrum(spectrum, mz_min, mz_max)
            ms1.rt_list.append(RT)
            ms1.spectra.append((mz_array, intensity_array))
        elif spectrum[mslevel_string] == 2: 
            if idx == 0:  # If the data start with MS2
                RT = 0
            precursor_mz = get_precursor_mz_from_rawdata_spectrum(spectrum)
            mz_array, intensity_array = filter_spectrum(spectrum, mz_min, mz_max)
            win_id = calc_win_id(precursor_mz, win_range)
            ms2[win_id].rt_list.append(RT)
            ms2[win_id].spectra.append((mz_array, intensity_array))

    # If the data start with MS2
    for each_ms2 in ms2:
        if (len(each_ms2.rt_list) - len(ms1.rt_list) == 1) and (each_ms2.rt_list == 0):
            each_ms2.rt_list.pop(0) 
            each_ms2.spectra.pop(0)

    # If the last cycle is imcomplete
    for each_ms2 in ms2:
        if len(ms1.rt_list) - len(each_ms2.rt_list) == 1:
            shorter_length = len(each_ms2.rt_list)
            
            for each_ms2_to_pop in ms2:
                if len(each_ms2_to_pop.rt_list) > shorter_length:
                    each_ms2_to_pop.rt_list.pop()
                    each_ms2_to_pop.spectra.pop()
            ms1.rt_list.pop()
            ms1.spectra.pop()
            break

    return ms1, ms2, win_range

def smooth_array(arr):
    if arr.shape[1] <= 1:
        return arr
    new_arr = np.zeros(arr.shape)
    # the first column
    new_arr[:, 0] = 2 / 3 * arr[:, 0] + 1 / 3 * arr[:, 1]
    # the last column
    new_arr[:, arr.shape[1] - 1] = 2 / 3 * arr[:, arr.shape[1] - 1] + 1 / 3 * arr[:, arr.shape[1] - 2]
    # columns in the middle
    for i in range(1, arr.shape[1] - 1):
        new_arr[:, i] = 0.5 * arr[:, i] + 0.25 * (arr[:, i + 1] + arr[:, i - 1])
    
    return new_arr

def calc_XIC(spectra, mz_to_extract, mz_unit, mz_tol):
    if mz_unit == "Da":
        extract_width = [mz_to_extract - mz_tol / 2, mz_to_extract + mz_tol / 2]
    elif mz_unit == "ppm":
        mz_tol_da = mz_to_extract * mz_tol * 0.000001
        extract_width = [mz_to_extract - mz_tol_da / 2, mz_to_extract + mz_tol_da / 2]
    xic = [sum(intensity_array[bisect.bisect_left(mz_array, extract_width[0]) : bisect.bisect_right(mz_array, extract_width[1])]) for mz_array, intensity_array in spectra]
    return xic

def filter_matrix(matrix):
    matrix = matrix.astype(float)
    # filter1
    matrix = matrix[np.sum(matrix, axis=1) >= 200] 
    # filter2
    ms2_max_list = np.max(matrix, axis=1)          
    matrix[matrix == 0] = np.inf
    ms2_min_list = np.min(matrix, axis=1)  
    matrix[matrix == np.inf] = 0
    matrix = matrix[ms2_max_list / ms2_min_list >= 1.5]
    return matrix

def adjust_size(frag_matrix, n_frags):
    # choose topN fragments according to the sum of the intensities
    if frag_matrix.shape[0] > n_frags:
        frag_sum = frag_matrix.sum(axis = 1)
        frag_selected = frag_sum.argsort()[::-1][0 : n_frags]
        return frag_matrix[frag_selected]    
    return frag_matrix

def find_rt_pos(RT, rt_list, n_cycles):
    middle_pos = np.argmin(np.abs(np.array(rt_list) - RT))
    expand_range = n_cycles // 2
    start_pos = middle_pos - expand_range
    
    if n_cycles % 2 == 0:        
        end_pos = middle_pos + expand_range
    else:
        end_pos = middle_pos + expand_range + 1
        
    if start_pos < 0:
        rt_pos = [i for i in range(n_cycles)]
    elif end_pos > len(rt_list):
        rt_pos = [i for i in range(len(rt_list) - n_cycles, len(rt_list))]
    else:
        rt_pos = [i for i in range(start_pos, end_pos)]
    return rt_pos

def calc_area(frag_chrom, rt_list_diff):
    trapezoids = 0
    for i in range(len(rt_list_diff)):
        trapezoids += (frag_chrom[i] + frag_chrom[i + 1]) * rt_list_diff[i]
    return trapezoids / 2

def get_peak_indice(n_cycles, peak_index_range):
    peak_indice = [n_cycles // 2]
    for i in range(peak_index_range - 1):
        if n_cycles % 2 != 0:
            peak_indice.append(n_cycles // 2 - (i + 1))
            peak_indice.append(n_cycles // 2 + (i + 1))
        else:
            peak_indice.append(n_cycles // 2 - (i + 1))
            if i:
                peak_indice.append(n_cycles // 2 + i)
    return peak_indice

def cos_sim(array_1, array_2):
    return cosine_similarity(np.array(array_1).reshape(1, -1), np.array(array_2).reshape(1, -1))[0][0]