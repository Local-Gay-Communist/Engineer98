use super::error::{ImageError, Result};
use super::geometry::Geometry;
use super::partition::{self, Partition};
use super::DiskImage;

const HDI_MIN_HEADER: usize = 32;

pub struct HdiImage {
    data: Vec<u8>,
    data_offset: usize,
    geom: Geometry,
}

impl HdiImage {
    pub fn from_bytes(data: Vec<u8>) -> Result<Self> {
        if data.len() < HDI_MIN_HEADER {
            return Err(ImageError::Truncated {
                expected: HDI_MIN_HEADER,
                actual: data.len(),
            });
        }
        let header_size = read_u32(&data, 0x08) as usize;
        let sector_size = read_u32(&data, 0x10);
        let sectors = read_u32(&data, 0x14);
        let heads = read_u32(&data, 0x18);
        let cylinders = read_u32(&data, 0x1C);

        if header_size < HDI_MIN_HEADER || header_size > data.len() {
            return Err(ImageError::BadGeometry {
                field: "header_size",
                value: header_size as u64,
            });
        }
        if sector_size == 0 || sectors == 0 || heads == 0 || cylinders == 0 {
            return Err(ImageError::BadGeometry {
                field: "sectors/heads/cylinders",
                value: 0,
            });
        }

        let geom = Geometry {
            cylinders,
            heads,
            sectors_per_track: sectors,
            sector_size,
        };

        Ok(Self {
            data,
            data_offset: header_size,
            geom,
        })
    }
}

impl DiskImage for HdiImage {
    fn geometry(&self) -> Geometry {
        self.geom
    }

    fn read_sector(&self, lba: u32) -> Result<Vec<u8>> {
        let total = self.geom.total_sectors();
        if lba >= total {
            return Err(ImageError::OutOfRange { lba, max: total - 1 });
        }
        let size = self.geom.sector_size as usize;
        let start = self.data_offset + lba as usize * size;
        let end = start + size;
        if end > self.data.len() {
            return Err(ImageError::Truncated {
                expected: end,
                actual: self.data.len(),
            });
        }
        Ok(self.data[start..end].to_vec())
    }

    fn partitions(&self) -> Result<Vec<Partition>> {
        partition::read_ipl1(&self.data, self.data_offset, self.geom)
    }

    fn format_name(&self) -> &'static str {
        "HDI (Anex86)"
    }
}

fn read_u32(data: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([
        data[off], data[off + 1], data[off + 2], data[off + 3],
    ])
}