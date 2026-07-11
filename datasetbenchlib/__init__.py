"""datasetbenchlib -- the API plugins import to talk back to DatasetBench.

Currently exposes:
    from datasetbenchlib import dialog

    dialog.write("some help text")
    values = dialog.request({"x_i": 0, "x_f": 100})

See datasetbenchlib/dialog.py for the full contract.
"""
