//! Engineer98 core analysis engine.
//!
//! This crate is exposed to Python as the `engineer98._core` module.

use pyo3::prelude::*;

/// Return the crate version as defined in Cargo.toml.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}