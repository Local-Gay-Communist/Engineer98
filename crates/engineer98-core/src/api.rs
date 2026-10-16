//! Python-facing wrappers for the image layer.
//!
//! The Rust core works with the `DiskImage` trait and its value types.
//! This module wraps them in `#[pyclass]` types so Python can hold a
//! reference to an opened image and query it as a structured object,
//! rather than round-tripping through formatted strings.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::image::{
    self, DiskImage, Geometry as RustGeometry, ImageError, Partition as RustPartition,
};

fn to_pyerr(e: ImageError) -> PyErr {
    PyValueError::new_err(e.to_string())
}

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

/// An opened PC-98 disk image.
///
/// Holds the parsed `Box<dyn DiskImage>` internally. Marked `Send` so it can
/// be moved across Python threads — useful later for background loading in
/// the GUI.
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