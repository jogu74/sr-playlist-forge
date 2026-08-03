"""Keep PyInstaller from collecting every optional fsspec backend.

SR Playlist Forge only uses UnityPy's LocalFileSystem integration. The
community fsspec hook collects cloud, database, dataframe, and scientific
backends that are unrelated to this application.
"""

hiddenimports = ["fsspec.implementations.local"]
