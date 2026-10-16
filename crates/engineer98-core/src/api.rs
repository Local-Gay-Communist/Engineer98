//! Python-facing wrappers for the image and executable layers.
//!
//! The Rust core works with the `DiskImage` trait and its value types.
//! This module wraps them in `#[pyclass]` types so Python can hold a
//! reference to an opened image or executable and query it as a
//! structured object, rather than round-tripping through formatted strings.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::exe::ExeFile;
use crate::image::{
    self, DiskImage, Geometry as RustGeometry, ImageError, Partition as RustPartition,
};

fn to_pyerr(e: ImageError) -> PyErr {
    PyValueError::new_err(e.to_string())
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

/// Geometry of a PC-98 disk: cylinders × heads × sectors-per-track × sector-size.
#[pyclass(name = "Geometry", module = "engineer98._core", frozen)]
#[derive(Clone)]
pub struct PyGeometry {
    #[pyo3(get)]
    pub cylinders: u32,
    #[pyo3(get)]
    pub heads: u32,
    #[pyo3(get)]
    pub sectors_per_track: u32,
    #[pyo3(get)]
    pub sector_size: u32,
}

#[pymethods]
impl PyGeometry {
    fn total_sectors(&self) -> u32 {
        self.cylinders * self.heads * self.sectors_per_track
    }

    fn total_bytes(&self) -> u64 {
        self.total_sectors() as u64 * self.sector_size as u64
    }

    fn __repr__(&self) -> String {
        format!(
            "Geometry(cylinders={}, heads={}, sectors_per_track={}, sector_size={})",
            self.cylinders, self.heads, self.sectors_per_track, self.sector_size,
        )
    }
}

impl From<RustGeometry> for PyGeometry {
    fn from(g: RustGeometry) -> Self {
        Self {
            cylinders: g.cylinders,
            heads: g.heads,
            sectors_per_track: g.sectors_per_track,
            sector_size: g.sector_size,
        }
    }
}

// ---------------------------------------------------------------------------
// Partition
// ---------------------------------------------------------------------------

/// One entry from a PC-98 IPL1 partition table.
#[pyclass(name = "Partition", module = "engineer98._core", frozen)]
#[derive(Clone)]
pub struct PyPartition {
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub start_lba: u32,
    #[pyo3(get)]
    pub sector_count: u32,
    #[pyo3(get)]
    pub bootable: bool,
}

#[pymethods]
impl PyPartition {
    /// Byte offset of this partition's first sector, relative to the data area.
    fn byte_offset(&self, sector_size: u32) -> u64 {
        self.start_lba as u64 * sector_size as u64
    }

    fn __repr__(&self) -> String {
        format!(
            "Partition(name={:?}, start_lba={}, sectors={}, bootable={})",
            self.name, self.start_lba, self.sector_count, self.bootable,
        )
    }
}

impl From<RustPartition> for PyPartition {
    fn from(p: RustPartition) -> Self {
        Self {
            name: p.name,
            start_lba: p.start_lba,
            sector_count: p.sector_count,
            bootable: p.bootable,
        }
    }
}

// ---------------------------------------------------------------------------
// Image
// ---------------------------------------------------------------------------

/// An opened PC-98 disk image.
///
/// Holds the parsed `Box<dyn DiskImage>` internally. Marked `Send`/`Sync`
/// through the trait bound so it can be moved across Python threads —
/// useful later for background loading in the GUI.
#[pyclass(name = "Image", module = "engineer98._core")]
pub struct PyImage {
    inner: Box<dyn DiskImage>,
}

#[pymethods]
impl PyImage {
    /// Open a disk image file and detect its format.
    #[staticmethod]
    fn open(path: &str) -> PyResult<Self> {
        let inner = image::open(path).map_err(to_pyerr)?;
        Ok(Self { inner })
    }

    /// The detected format's human-readable name.
    fn format_name(&self) -> &'static str {
        self.inner.format_name()
    }

    fn geometry(&self) -> PyGeometry {
        self.inner.geometry().into()
    }

    /// Partitions declared in the IPL1 table (empty for floppy formats).
    fn partitions(&self) -> PyResult<Vec<PyPartition>> {
        let parts = self.inner.partitions().map_err(to_pyerr)?;
        Ok(parts.into_iter().map(Into::into).collect())
    }

    /// Read a single sector by linear address. Returns `bytes`.
    fn read_sector(&self, lba: u32) -> PyResult<Vec<u8>> {
        self.inner.read_sector(lba).map_err(to_pyerr)
    }

    /// Read `count` contiguous sectors starting at `lba`. Returns `bytes`.
    fn read_sectors(&self, lba: u32, count: u32) -> PyResult<Vec<u8>> {
        self.inner.read_sectors(lba, count).map_err(to_pyerr)
    }

    fn __repr__(&self) -> String {
        let g = self.inner.geometry();
        format!(
            "<engineer98.Image format={:?} geometry={}x{}x{}x{}>",
            self.inner.format_name(),
            g.cylinders,
            g.heads,
            g.sectors_per_track,
            g.sector_size,
        )
    }
}

// ---------------------------------------------------------------------------
// ExeFile
// ---------------------------------------------------------------------------

/// A parsed DOS MZ executable.
#[pyclass(name = "ExeFile", module = "engineer98._core")]
pub struct PyExeFile {
    inner: ExeFile,
}

#[pymethods]
impl PyExeFile {
    /// Open a DOS MZ executable from a file path.
    #[staticmethod]
    fn open(path: &str) -> PyResult<Self> {
        let data = std::fs::read(path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        let inner = ExeFile::from_bytes(data).map_err(to_pyerr)?;
        Ok(Self { inner })
    }

    /// Parse a DOS MZ executable from an in-memory byte buffer.
    #[staticmethod]
    fn from_bytes(data: &[u8]) -> PyResult<Self> {
        let inner = ExeFile::from_bytes(data.to_vec()).map_err(to_pyerr)?;
        Ok(Self { inner })
    }

    #[getter]
    fn entry_cs(&self) -> u16 {
        self.inner.header.initial_cs
    }

    #[getter]
    fn entry_ip(&self) -> u16 {
        self.inner.header.initial_ip
    }

    #[getter]
    fn entry_module_offset(&self) -> u32 {
        self.inner.header.entry_module_offset()
    }

    #[getter]
    fn entry_file_offset(&self) -> u32 {
        self.inner.header.entry_file_offset()
    }

    #[getter]
    fn initial_ss(&self) -> u16 {
        self.inner.header.initial_ss
    }

    #[getter]
    fn initial_sp(&self) -> u16 {
        self.inner.header.initial_sp
    }

    #[getter]
    fn header_bytes(&self) -> u32 {
        self.inner.header.header_bytes()
    }

    #[getter]
    fn load_module_bytes(&self) -> u32 {
        self.inner.header.load_module_bytes()
    }

    #[getter]
    fn reloc_count(&self) -> u16 {
        self.inner.header.reloc_count
    }

    /// The relocation table as a list of `(offset, segment)` pairs.
    fn relocations(&self) -> Vec<(u16, u16)> {
        self.inner.relocations()
    }

    /// Read `length` bytes from the executable at absolute file offset `offset`.
    fn read_at(&self, offset: u32, length: u32) -> PyResult<Vec<u8>> {
        self.inner
            .read_at(offset, length)
            .map(|s| s.to_vec())
            .map_err(to_pyerr)
    }

    /// The entire load module (header-stripped executable image).
    fn code_bytes(&self) -> Vec<u8> {
        self.inner.code_bytes().to_vec()
    }

    fn __repr__(&self) -> String {
        format!(
            "<engineer98.ExeFile entry={:04x}:{:04x} load_module={} bytes, relocs={}>",
            self.inner.header.initial_cs,
            self.inner.header.initial_ip,
            self.inner.header.load_module_bytes(),
            self.inner.header.reloc_count,
        )
    }
}