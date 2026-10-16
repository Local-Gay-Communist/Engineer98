use super::error::{ImageError, Result};
use super::geometry::Geometry;
use super::partition::Partition;
use super::DiskImage;

/// A raw sector dump with no header. Geometry is guessed from the file size
/// using the most common PC-98 2HD floppy geometry (1024-byte sectors,
/// 8 sectors/track, 2 heads, 77 cylinders = 1,261,568 bytes), or a
/// 512-byte-sector hard disk layout otherwise.
pub struct RawImage {
    data: Vec<u8>,
    geom: Geometry,
}

const PC98_2HD_SIZE: usize = 1_261_568;
const PC98_2HD_SECTOR: u32 = 1024;
const PC98_2HD_SPT: u32 = 8;
const PC98_2HD_HEADS: u32 = 2;
const PC98_2HD_CYLS: u32 = 77;

impl RawImage {
    pub fn from_bytes(data: Vec<u8>) -> Result<Self> {
        let geom = if data.len() == PC98_2HD_SIZE {
            Geometry {
                cylinders: PC98_2HD_CYLS,
                heads: PC98_2HD_HEADS,
                sectors_per_track: PC98_2HD_SPT,
                sector_size: PC98_2HD_SECTOR,
            }
        } else if data.len() % 512 == 0 {
            // Assume a 512-byte-sector HDD layout with a standard geometry.
            let total = (data.len() / 512) as u32;
            Geometry {
                cylinders: total / (16 * 63),
                heads: 16,
                sectors_per_track: 63,
                sector_size: 512,
            }
        } else {
            return Err(ImageError::Unsupported("raw image with unknown geometry"));
        };

        Ok(Self { data, geom })
    }
}

impl DiskImage for RawImage {
    fn geometry(&self) -> Geometry {
        self.geom
    }

    fn read_sector(&self, lba: u32) -> Result<Vec<u8>> {
        let total = self.geom.total_sectors();
        if lba >= total {
            return Err(ImageError::OutOfRange { lba, max: total - 1 });
        }
        let size = self.geom.sector_size as usize;
        let start = lba as usize * size;
        let end = (start + size).min(self.data.len());
        Ok(self.data[start..end].to_vec())
    }

    fn partitions(&self) -> Result<Vec<Partition>> {
        // Try IPL1 if the first sector looks like a PC-98 MBR.
        if self.data.len() >= 512 && self.data[0] == 0xEB {
            super::partition::read_ipl1(&self.data, 0, self.geom)
        } else {
            Ok(Vec::new())
        }
    }

    fn format_name(&self) -> &'static str {
        "Raw"
    }
}