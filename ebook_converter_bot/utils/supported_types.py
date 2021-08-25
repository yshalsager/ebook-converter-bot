SUPPORTED_INPUT_TYPES = ['azw', 'azw3', 'azw4', 'cb7', 'cbc', 'cbr', 'cbz', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz',
                         'html', 'htmlz', 'kfx', 'lit', 'lrf', 'mobi', 'odt', 'pdb', 'pdf', 'pml', 'prc', 'rb', 'rtf',
                         'snb', 'tcr', 'txt', 'txtz']

SUPPORTED_OUTPUT_TYPES = ['azw3', 'docx', 'epub', 'fb2', 'htmlz', 'kfx', 'lit', 'lrf', 'mobi', 'oeb', 'pdb', 'pdf',
                          'pmlz', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz', 'zip']


def is_supported_input_type(filename):
    return filename.lower().split('.')[-1] in SUPPORTED_INPUT_TYPES
