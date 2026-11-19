# Changes made after testing started (disclosed)

1. **Resolvability rule (bug of the declared rule, found on the development set).** The declared rule judged ">= 2 voxels
   in at least two axes" from run lengths through the voxel. Those runs count the structure's LENGTH, so a one-slice sheet or
   tube passed as resolvable (thin_aniso: 1 slice, reported resolvable). Replaced by: not resolvable when the structure
   occupies <= 1 slice at that voxel AND its in-plane width there is < 2 x slice thickness. The constant 2 is the sampling
   argument of the declared rule, not fitted. Found on: original thin_aniso phantom (development set).
