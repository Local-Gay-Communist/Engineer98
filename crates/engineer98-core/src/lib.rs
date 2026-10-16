//! Engineer98 core analysis engine.
//!
//! This crate is exposed to Python as the `engineer98._core` module.

use pyo3::prelude::*;

pub mod api;
pub mod exe;
pub mod image;

/// Return the crate version as defined in Cargo.toml.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_class::<api::PyImage>()?;
    m.add_class::<api::PyGeometry>()?;
    m.add_class::<api::PyPartition>()?;
    m.add_class::<api::PyExeFile>()?;
    Ok(())
}