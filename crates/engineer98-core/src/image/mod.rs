pub mod error;
pub mod geometry;
mod hdi;
mod fdi;
mod d88;
mod raw;
mod partition;

pub use error::{ImageError, Result};
pub use geometry::{CHS, Geometry};
pub use partition::Partition;

use std::path::Path;

/// A read-only view of a PC-98 disk image, regardless of container format.
pub trait DiskImage: Send + Sync {
    fn geometry(&self) -> Geometry;

    /// Read one sector by linear address. Returns the raw sector bytes.
    fn read_sector(&self, lba: u32) -> Result<Vec<u8>>;

    /// Read `count` contiguous sectors starting at `lba`.
    fn read_sectors(&self, lba: u32, count: u32) -> Result<Vec<u8>> {
        let size = self.geometry().sector_size as usize;
        let mut out = Vec::with_capacity(size * count as usize);
        for i in 0..count {
            out.extend_from_slice(&self.read_sector(lba + i)?);
        }
        Ok(out)
    }

    /// Partitions declared in the IPL1 table, if this image has one.
    fn partitions(&self) -> Result<Vec<Partition>>;

    /// Human-readable format name, for logs and the GUI.
    fn format_name(&self) -> &'static str;
}

/// Open a disk image, detecting the format from the file header.
pub fn open(path: impl AsRef<Path>) -> Result<Box<dyn DiskImage>> {
    let data = std::fs::read(path.as_ref())?;
    detect(data)
}

/// Detect format from owned raw bytes and construct the right impl.
///
/// Takes `Vec<u8>` so the buffer can be moved into whichever parser
/// matched, avoiding a full copy of the image.
pub fn detect(data: Vec<u8>) -> Result<Box<dyn DiskImage>> {
    let peek: &[u8] = &data;

    // Anex86 HDI and FDI share the same header layout. The only reliable
    // difference is convention: FDI is used for floppies, HDI for hard disks.
    // Discriminate by file size — floppies are never more than ~4 MB.
    if peek.len() >= 32 && looks_like_anex86(peek) {
        let label_is_hdd = peek.len() > 4 * 1024 * 1024;
        if label_is_hdd {
            return hdi::HdiImage::from_bytes(data).map(|i| Box::new(i) as _);
        } else {
            return fdi::FdiImage::from_bytes(data).map(|i| Box::new(i) as _);
        }
    }

    // D88 identification: little-endian u32 at 0x20 must be 0x02A0 or 0x02B0.
    if peek.len() >= 0x2B0 {
        let track0 = read_u32(peek, 0x20);
        if track0 == 0x02A0 || track0 == 0x02B0 {
            return d88::D88Image::from_bytes(data).map(|i| Box::new(i) as _);
        }
    }

    raw::RawImage::from_bytes(data).map(|i| Box::new(i) as _)
}

fn looks_like_anex86(data: &[u8]) -> bool {
    let hdr_size = read_u32(data, 0x08);
    let sec_size = read_u32(data, 0x10);
    let sectors  = read_u32(data, 0x14);
    let heads    = read_u32(data, 0x18);
    let cyls     = read_u32(data, 0x1C);
    matches!(hdr_size, 4096 | 512 | 1024)
        && matches!(sec_size, 256 | 512 | 1024)
        && sectors > 0
        && heads > 0
        && cyls > 0
}

fn read_u32(data: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([
        data[off], data[off + 1], data[off + 2], data[off + 3],
    ])
}