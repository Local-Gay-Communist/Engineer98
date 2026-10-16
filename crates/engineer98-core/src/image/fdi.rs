use super::error::{ImageError, Result};
use super::geometry::Geometry;
use super::partition::Partition;
use super::DiskImage;

/// FDI always has a 4096-byte header; only the first 32 bytes are meaningful.
const FDI_HEADER_SIZE: usize = 4096;

pub struct FdiImage {
    data: Vec<u8>,
    geom: Geometry,
}

impl FdiImage {
    pub fn from_bytes(data: Vec<u8>) -> Result<Self> {
        if data.len() < FDI_HEADER_SIZE {
            return Err(ImageError::Truncated {
                expected: FDI_HEADER_SIZE,
                actual: data.len(),
            });
        }
        let sector_size = read_u32(&data, 0x10);
        let sectors = read_u32(&data, 0x14);
        let heads = read_u32(&data, 0x18);
        let cylinders = read_u32(&data, 0x1C);

        if sector_size == 0 || sectors == 0 || heads == 0 || cylinders == 0 {
            return Err(ImageError::BadGeometry {
                field: "fdi geometry",
                value: 0,
            });
        }

        Ok(Self {
            data,
            geom: Geometry {
                cylinders,
                heads,
                sectors_per_track: sectors,
                sector_size,
            },
        })
    }
}

impl DiskImage for FdiImage {
    fn geometry(&self) -> Geometry {
        self.geom
    }

    fn read_sector(&self, lba: u32) -> Result<Vec<u8>> {
        let total = self.geom.total_sectors();
        if lba >= total {
            return Err(ImageError::OutOfRange { lba, max: total - 1 });
        }
        let size = self.geom.sector_size as usize;
        let start = FDI_HEADER_SIZE + lba as usize * size;
        let end = start + size;
        if end > self.data.len() {
            return Err(ImageError::Truncated {
                expected: end,
                actual: self.data.len(),
            });
        }
        Ok(self.data[start..end].to_vec())
    }

    /// FDI is a floppy format; IPL1 partitions are a hard-disk concept.
    fn partitions(&self) -> Result<Vec<Partition>> {
        Ok(Vec::new())
    }

    fn format_name(&self) -> &'static str {
        "FDI (Anex86 floppy)"
    }
}

fn read_u32(data: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([
        data[off], data[off + 1], data[off + 2], data[off + 3],
    ])
}