## Modified from PECAN's peptideCalculator.py

import re
import numpy as np

"""######## Reference masses and amino acids compositions ########"""
# 1. Mono masses of each atom
mono_masses = dict()
mono_masses['H'] = 1.007825035
mono_masses['C'] = 12.00000
mono_masses['O'] = 15.99491463
mono_masses['N'] = 14.003074
mono_masses['I'] = 126.904473
mono_masses['S'] = 31.9720707
mono_masses['P'] = 30.973762
mono_masses['13C'] = 13.0033554  # heavy 13C
mono_masses['15N'] = 15.0001088  # heavy 15N

# 2. Important group masses
proton_mass = 1.00727646677
OH_mass = mono_masses['O'] + mono_masses['H']
H2O_mass = mono_masses['O'] + 2*(mono_masses['H'])
NH3_mass = mono_masses['N'] + 3*(mono_masses['H'])
CO_mass = mono_masses['C'] + mono_masses['O']
cam_mass = 2*mono_masses['C'] + 3*mono_masses['H'] + mono_masses['O'] + mono_masses['N']

# 3. Amino acids compositions
residue_composition = dict()   # all residue compositions are -H2O
residue_composition['A'] = {'H': 5,  'C': 3,  'O': 1, 'N': 1}
# residue_composition['C'] = {'H': 8,  'C': 5,  'O': 2, 'N': 2, 'S': 1}  ## with cam iodoacetamide
residue_composition['C'] = {'H': 5,  'C': 3,  'O': 1, 'N': 1, 'S': 1}  # no modification!
residue_composition['D'] = {'H': 5,  'C': 4,  'O': 3, 'N': 1}
residue_composition['E'] = {'H': 7,  'C': 5,  'O': 3, 'N': 1}
residue_composition['F'] = {'H': 9,  'C': 9,  'O': 1, 'N': 1}
residue_composition['G'] = {'H': 3,  'C': 2,  'O': 1, 'N': 1}
residue_composition['H'] = {'H': 7,  'C': 6,  'O': 1, 'N': 3}
residue_composition['I'] = {'H': 11, 'C': 6,  'O': 1, 'N': 1}
residue_composition['K'] = {'H': 12, 'C': 6,  'O': 1, 'N': 2}
residue_composition['L'] = {'H': 11, 'C': 6,  'O': 1, 'N': 1}
residue_composition['M'] = {'H': 9,  'C': 5,  'O': 1, 'N': 1, 'S': 1}
residue_composition['N'] = {'H': 6,  'C': 4,  'O': 2, 'N': 2}
residue_composition['P'] = {'H': 7,  'C': 5,  'O': 1, 'N': 1}
residue_composition['Q'] = {'H': 8,  'C': 5,  'O': 2, 'N': 2}
residue_composition['R'] = {'H': 12, 'C': 6,  'O': 1, 'N': 4}
residue_composition['S'] = {'H': 5,  'C': 3,  'O': 2, 'N': 1}
residue_composition['T'] = {'H': 7,  'C': 4,  'O': 2, 'N': 1}
residue_composition['U'] = {'H': 5,  'C': 3,  'O': 1, 'N': 1}   # and 'Se':1
residue_composition['V'] = {'H': 9,  'C': 5,  'O': 1, 'N': 1}
residue_composition['W'] = {'H': 10, 'C': 11, 'O': 1, 'N': 2}
residue_composition['Y'] = {'H': 9,  'C': 9,  'O': 2, 'N': 1}
residue_composition['X'] = {'H': 11, 'C': 6,  'O': 1, 'N': 1}   # L or I
residue_composition['Z'] = {'H':999, 'C':999, 'O':999,'N':999}  # E or Q, differ by 1 Da, always ignored
# heavy labeled c-terminal R, K
residue_composition['B'] = {'H': 12, '13C': 6,  'O': 1, '15N': 4}
residue_composition['J'] = {'H': 12, '13C': 6,  'O': 1, '15N': 2}

def precompute_fragment_mass():
    all_seqchars = "ABCDEFGHIJKLMNPQRSTUVWXYZ"
    fragment_mass_precomput = dict()
    for aa in all_seqchars:
        fragment_mass_aa = 0
        for el in residue_composition[aa]:
            fragment_mass_aa += residue_composition[aa][el]*mono_masses[el]
        fragment_mass_precomput[aa] = fragment_mass_aa
    return fragment_mass_precomput

FRAGMENT_MASS_DICT = precompute_fragment_mass()

# UniMod PTMs
unimod1_mass = 2 * mono_masses['C'] + mono_masses['O'] + 2 * mono_masses['H']  # beginning
unimod4_mass = 57.021464  # CH3CNO, modification of C
unimod5_mass = mono_masses['C'] + mono_masses['N'] + mono_masses['O']  # CHNO - H  # beginning
unimod21_mass = mono_masses['H'] + 3 * mono_masses['O'] + mono_masses['P']  # modification of S
unimod26_mass = 2 * mono_masses['C'] + mono_masses['O']  # modification of C
unimod27_mass = -2 * mono_masses['H'] - mono_masses['O']  # modification of E
unimod28_mass = -3 * mono_masses['H'] - mono_masses['N']  # modification of Q
unimod35_mass = 15.994915  # modification of M
unimod259_mass = mono_masses["13C"] * 6 - mono_masses["C"] * 6 + mono_masses["15N"] * 2 - mono_masses["N"] * 2 # modification of K
unimod267_mass = mono_masses["13C"] * 6 - mono_masses["C"] * 6 + mono_masses["15N"] * 4 - mono_masses["N"] * 4 # modification of R

"""#############################################################"""

def calc_fragment_mz(full_seq, pure_peptide_seq, charge, ion_type):
    """
    Calculate fragment ion m/z.
    ATTENTION:
    If you want to calculate precursor m/z, input ion_type as "yM" where M is the length of the peptide.
    @Input: full_seq, peptide sequence string in UniMod format.
    @Input: pure_peptide_seq, peptdie sequence without any modifications.
    @Input: fragment charge, 1 or 2.
    @Input: ion_type, "yn" or "bn".
    @Output: m/z of the fragment ion.
    """
    # slice the fragment sequence
    fragment_length = int(ion_type[1:])
    
    if ion_type[0] == "b":
        re_pattern = "^(\(UniMod:\d+\))*" + "(\(UniMod:\d+\))*".join(list(pure_peptide_seq[ : fragment_length])) + "(\(UniMod:\d+\))*"        
    else:
        re_pattern = "(\(UniMod:\d+\))*".join(list(pure_peptide_seq[-fragment_length : ])) + "(\(UniMod:\d+\))*$"
        if fragment_length == len(pure_peptide_seq):
            re_pattern = "^(\(UniMod:\d+\))*" + re_pattern
    fragment_seq = re.search(re_pattern, full_seq).group()
    #print(fragment_seq)
    pure_fragment_seq = re.sub(r"\(UniMod:\d+\)", "", fragment_seq)
    
    unimod1_count = fragment_seq.count("(UniMod:1)")
    unimod4_count = fragment_seq.count("(UniMod:4)")
    unimod5_count = fragment_seq.count("(UniMod:5)")
    unimod21_count = fragment_seq.count("(UniMod:21)")
    unimod26_count = fragment_seq.count("(UniMod:26)")
    unimod27_count = fragment_seq.count("(UniMod:27)")
    unimod28_count = fragment_seq.count("(UniMod:28)")
    unimod35_count = fragment_seq.count("(UniMod:35)")
    unimod259_count = fragment_seq.count("(UniMod:259)")
    unimod267_count = fragment_seq.count("(UniMod:267)")
    
    # calculate m/z
    fragment_mass = sum([FRAGMENT_MASS_DICT[aa] for aa in pure_fragment_seq])                
    
    if ion_type.startswith("y"):
        fragment_mass += H2O_mass
    
    fragment_mass += (unimod1_count * unimod1_mass + 
                      unimod4_count * unimod4_mass + 
                      unimod5_count * unimod5_mass + 
                      unimod35_count * unimod35_mass + 
                      unimod28_count * unimod28_mass + 
                      unimod21_count * unimod21_mass + 
                      unimod259_count * unimod259_mass + 
                      unimod267_count * unimod267_mass + 
                      unimod26_count * unimod26_mass + 
                      unimod27_count * unimod27_mass)

    return (fragment_mass + (charge * proton_mass)) / charge

def calc_all_fragment_mzs(full_seq, precursor_charge, 
                          fragment_mz_limit = (99, 1801), b_start = 1, y_start = 2, 
                          return_charges = False):
    """
    Calculate all fragment ions' m/z of a precursor
    @Input full_seq: peptide sequence string in UniMod format.
    @Input precursor_charge: charge of precursor.
    @Input fragment_mz_limit: m/z range of fragment ions to keep for output.
    @Input b_start: shortest sequence of b-series ions.
    @Input y_start: shortest sequence of y-series ions.
    @Output: a list of m/z values.
    """
    fragment_mzs = []
    fragment_charges = []

    pure_peptide_seq = re.sub(r"\(UniMod:\d+\)", "", full_seq)
    peptide_length = len(pure_peptide_seq)
    
    for i in range(b_start, peptide_length + 1):
        if i >= y_start: 
            fragment_mzs.append(calc_fragment_mz(full_seq, pure_peptide_seq, 1, "y%d" % i))
            fragment_charges.append(1)                       
        fragment_mzs.append(calc_fragment_mz(full_seq, pure_peptide_seq, 1, "b%d" % i))
        fragment_charges.append(1)
            
        if precursor_charge > 2:
            if i >= y_start:
                fragment_mzs.append(calc_fragment_mz(full_seq, pure_peptide_seq, 2, "y%d" % i))
                fragment_charges.append(2)
            fragment_mzs.append(calc_fragment_mz(full_seq, pure_peptide_seq, 2, "b%d" % i))
            fragment_charges.append(2)

    fragment_mzs = np.array(fragment_mzs)
    index = (fragment_mzs >= fragment_mz_limit[0]) & (fragment_mzs <= fragment_mz_limit[1])
    fragment_mzs = fragment_mzs[index]
    fragment_charges = np.array(fragment_charges)[index]

    if return_charges:
        return fragment_mzs, fragment_charges
    return fragment_mzs