import platform
if platform.system() != "Windows":
    #Note pysam doesn't support Windows
    import numpy as np
    import anndata as ad
    import pandas as pd
    import pysam
    from scipy.sparse import lil_matrix, csr_matrix
    from tqdm import tqdm
    import gzip
    from ._features import make_windows


    def bld_mtx_fly(tsv_file, annotation, csv_file=None, genome=None, save=False):
        """
        Building count matrix on the fly.
        Expected running time for 10k cells X 100k features on a personal computer ~65min
        Does not count pcr duplicate.
        A tbi file with the same filename as the provided tsv_file must be present in the same directory as the tsv file
        Note that this function is not available on the Windows operating system.

        Parameters
        ----------

        tsv_file : name of the file containing the multiplexed reads (.tsv or .tsv.gz)

        annotation : loaded set of features to create the feature matrix from

        csv_file : default is None -

        genome : default is None - specify if you want to extract a specific genome assembly

        save : default is False - supply a file path as str to save generated AnnData object

        Output
        ------

        AnnData object (also saved as h5ad if save argument is specified)

        """

        print('loading barcodes')
        barcodes = sorted(pd.read_csv(tsv_file, sep='\t', header=None).loc[:, 3].unique().tolist())

        # barcodes
        nb_barcodes = len(barcodes)
        dict_barcodes = {barcodes[i]: i for i in range(0, len(barcodes))}

        # Load tabix
        tbx = pysam.TabixFile(tsv_file)

        # format annotations
        window_list = []

        if genome:
            for chrom in sorted(annotation.keys()):
                window_list += [["".join([genome, '_chr', chrom]), int(n[0]), int(n[1])] for n in annotation[chrom]]
        else:
            for chrom in sorted(annotation.keys()):
                window_list += [["".join(['chr', chrom]), int(n[0]), int(n[1])] for n in annotation[chrom]]

        print('building count matrix')
        mtx = lil_matrix((nb_barcodes, len(window_list)), dtype=np.float32)
        for i, tmp_feat in enumerate(tqdm(window_list)):
            for row in tbx.fetch(tmp_feat[0], tmp_feat[1], tmp_feat[2], parser=pysam.asTuple()):
                mtx[dict_barcodes[str(row).split('\t')[-2]], i] += 1

        print('building AnnData object')
        mtx = ad.AnnData(mtx.tocsr(),
                         obs=pd.DataFrame(index=barcodes),
                         var=pd.DataFrame(index=['_'.join([str(p) for p in n]) for n in window_list]))

        if csv_file:
            print('filtering barcodes')
            df = pd.read_csv(csv_file)
            if genome == 'mm10':
                df_filtered = df[(df.is_mm10_cell_barcode == 1)]
            elif genome == 'hg19':
                df_filtered = df[(df.is_hg19_cell_barcode == 1)]
            else:
                df_filtered = df[(df.is_cell_barcode == 1)]

            barcodes = set(df_filtered.barcode.tolist())
            mtx = mtx[[i in barcodes for i in mtx.obs.index]].copy()

        if save:
            mtx.write(save)

        return mtx


def get_barcodes(fragments,
                 comment="#"):

    if fragments.endswith(".gz"):
        fh = gzip.open(fragments, mode="rt")
    else:
        fh = open(fragments, mode="r")

    barcodes = set()

    check_for_comments = True
    use_strip = None

    for line in fh:

        # only check for comments at start - performance reasons
        if check_for_comments:
            if line.startswith(comment):
                continue
            else:
                check_for_comments = False

        # only strip if necessary - performance reasons
        if use_strip is None:
            line_split = line.strip().split("\t")
            if len(line_split) == 4:
                use_strip = True
            else:
                use_strip = False
        elif not use_strip:
            line_split = line.split("\t")
        else:
            line_split = line.strip().split("\t")

        bc = line_split[3]

        barcodes.add(bc)

    return list(barcodes)


def count(fragments,
          features,
          valid_bcs,
          fast,
          comment="#"):

    check_for_comments = True
    use_strip = None

    feature_idx = 0

    chrom_mapping = dict()
    bc_mapping = {bc: i for i, bc in enumerate(valid_bcs)}

    valid_bcs_set = set(valid_bcs)

    ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ##

    # fast vs memory efficient
    if fast:
        count_mtx = [[0 for _ in range(len(features))] for i in range(len(valid_bcs))]
        # count_mtx = np.zeros((len(valid_bcs), len(features)))
    else:
        count_mtx_sparse = lil_matrix((len(valid_bcs), len(features)))

    ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ##

    # mapping chromosome/contig names to numeric values
    c = 0
    for chrom in [feature[0] for feature in features]:
        if not chrom in chrom_mapping:
            chrom_mapping[chrom] = c
            c += 1

    ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ##

    if fragments.endswith(".gz"):
        fh = gzip.open(fragments, mode="rt")
    else:
        fh = open(fragments, mode="r")

    ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ##

    for line in fh:

        # only check for comments at start - performance reasons
        if check_for_comments:
            if line.startswith(comment):
                continue
            else:
                check_for_comments = False

        # only strip if necessary - performance reasons
        if use_strip is None:
            line_split = line.strip().split("\t")
            if len(line_split) == 4:
                use_strip = True
            else:
                use_strip = False
        elif not use_strip:
            line_split = line.split("\t")
        else:
            line_split = line.strip().split("\t")

        ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ##

        bc = line_split[3]
        if bc not in valid_bcs_set:
            continue

        ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ##

        chrom = line_split[0]

        # map chromosome/contig name to numeric value
        # skip if no features on chromosome/contig
        if chrom in chrom_mapping:
            chrom_int = chrom_mapping[chrom]
        else:
            continue

        # fragment on previous chromosome
        if chrom_int < chrom_mapping[features[feature_idx][0]]:
            continue
        # feature on previous chromosome
        elif chrom_int > chrom_mapping[features[feature_idx][0]]:
            while feature_idx < len(features) and chrom_int > chrom_mapping[features[feature_idx][0]]:
                feature_idx += 1
            if feature_idx >= len(features):
                break

        ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ## ##

        start = int(line_split[1])
        stop = int(line_split[2])

        # fragment in front of feature
        if stop < features[feature_idx][1]:
            continue

        # fragment behind feature
        elif start > features[feature_idx][2]:
            while feature_idx < len(features) and start > features[feature_idx][2] and chrom_int == chrom_mapping[features[feature_idx][0]]:
                feature_idx += 1

            # end of features
            if feature_idx >= len(features):
                break

            # fragment on previous chromosome
            elif chrom_int != chrom_mapping[features[feature_idx][0]]:
                continue

            # overlap
            elif not stop < features[feature_idx][1]:

                if fast:
                    count_mtx[bc_mapping[bc]][feature_idx] += 1
                else:
                    count_mtx_sparse[bc_mapping[bc], feature_idx] += 1

                tmp_idx = feature_idx + 1
                is_overlapping = True
                on_same_chrom = True

                # follow-up
                while tmp_idx < len(features) and is_overlapping and on_same_chrom:
                    is_overlapping = not (stop < features[tmp_idx][1] or start > features[tmp_idx][2])
                    on_same_chrom = chrom_int == chrom_mapping[features[tmp_idx][0]]

                    if is_overlapping and on_same_chrom:
                        if fast:
                            count_mtx[bc_mapping[bc]][tmp_idx] += 1
                        else:
                            count_mtx_sparse[bc_mapping[bc], tmp_idx] += 1

                    tmp_idx += 1

        # overlap
        else:

            if fast:
                count_mtx[bc_mapping[bc]][feature_idx] += 1
            else:
                count_mtx_sparse[bc_mapping[bc], feature_idx] += 1

            tmp_idx = feature_idx + 1
            is_overlapping = True
            on_same_chrom = True

            # follow-up
            while tmp_idx < len(features) and is_overlapping and on_same_chrom:
                is_overlapping = not (stop < features[tmp_idx][1] or start > features[tmp_idx][2])
                on_same_chrom = chrom_int == chrom_mapping[features[tmp_idx][0]]

                if is_overlapping and on_same_chrom:
                    if fast:
                        count_mtx[bc_mapping[bc]][tmp_idx] += 1
                    else:
                        count_mtx_sparse[bc_mapping[bc], tmp_idx] += 1

                tmp_idx += 1

    fh.close()

    if fast:
        return count_mtx
    else:
        return count_mtx_sparse


def peak_mtx(fragments_file,
             peak_file,
             valid_bcs=None,
             normalized_peak_size=None,
             fast=False):
    """
    Generates a count matrix based on peaks. The fragments file needs to be sorted.

    Args:
        fragments_file: path to fragments file
        peak_file: path to BED file
        valid_bcs: list of valid barcodes (optional)
        normalized_peak_size: if True peaks size will be normalized; default: None (no normalization)
        fast: if True dense matrix will be used (faster but required more memory); default: False (sparse matrix)

    Returns:
        AnnData object
    """

    names = ["chr", "start", "stop"]
    features = pd.read_csv(peak_file, sep="\t", header=None, usecols=[0, 1, 2], names=names, comment='#', dtype={"chr": str})

    try:
        int(features.iloc[0].start)
    except ValueError:
        features = features[1:].copy()
        features["start"] = features.start.astype(int)
        features["stop"] = features.stop.astype(int)



    features.index = features.apply(lambda row: "_".join([str(val) for val in row]), axis=1)

    if normalized_peak_size:
        extension = int(np.ceil(normalized_peak_size / 2))
        start = round(features["start"] + (features["stop"] - features["start"]) / 2).astype(int) - extension
        stop = round(features["start"] + (features["stop"] - features["start"]) / 2).astype(int) + extension
        features["start"] = start
        features["stop"] = stop
        features["start"].clip(lower=0, inplace=True)

    features.sort_values(by=["chr", "start", "stop"], key=lambda col: col if col.dtype == np.int64 else col.str.lower(), inplace=True)

    if valid_bcs is None:
        valid_bcs = get_barcodes(fragments_file)

    ct_mtx = count(fragments_file, features.values.tolist(), valid_bcs, fast)

    if fast:
        X = csr_matrix(ct_mtx)
    else:
        X = ct_mtx.tocsr()

    adata = ad.AnnData(X, obs=pd.DataFrame(index=valid_bcs), var=features)

    return adata


def gene_activity_mtx(fragments_file,
                      gtf_file,
                      valid_bcs=None,
                      upstream=2000,
                      downstream=0,
                      source=None,
                      gene_type=None,
                      fast=False):
    """
    Generates a count matrix based on the openness of the gene bodies and promoter regions (gene activity). The
    fragments file needs to be sorted.

    Args:
        fragments_file: path to fragments file
        gtf_file: path to GTF file
        valid_bcs: list of valid barcodes (optional)
        upstream: number of bp to consider upstream of TSS; default: 2000 bp
        downstream: number of bp to consider downstream of gene body; default: 0 bp
        source: filter for source of the feature; default: None (no filtering)
        gene_type: filter for gene type of the feature; default: None (no filtering)
        fast: if True dense matrix will be used (faster but required more memory); default: False (sparse matrix)

    Returns:
        AnnData object
    """

    names = ["chr", "source", "type", "start", "stop", "score", "strand", "frame", "attribute"]
    features = pd.read_csv(gtf_file, sep="\t", header=None, comment="#", names=names, dtype={"chr": str})

    features = features[features.type == "gene"]

    if source:
        features = features[features.source == source]

    features["gene_id"] = [attr.replace("gene_id", "").strip().strip("\"") for feature_attr in features.attribute for attr in feature_attr.split(";") if attr.strip().startswith("gene_id")]
    features["gene_name"] = [attr.replace("gene_name", "").strip().strip("\"") for feature_attr in features.attribute for attr in feature_attr.split(";") if attr.strip().startswith("gene_name")]
    features["gene_type"] = [attr.replace("gene_type", "").strip().strip("\"") for feature_attr in features.attribute for attr in feature_attr.split(";") if attr.strip().startswith("gene_type")]

    if gene_type:
        features = features[[feature in gene_type for feature in features.gene_type]]

    features.index = features.gene_id

    features["start"] = features.start - upstream
    features["start"].clip(lower=0, inplace=True)
    features["stop"] = features.stop + downstream

    features.sort_values(by=["chr", "start", "stop"], key=lambda col: col if col.dtype == np.int64 else col.str.lower(), inplace=True)

    features = features[["gene_name", "gene_id", "gene_type", "chr", "start", "stop", "strand", "source"]]

    if valid_bcs is None:
        valid_bcs = get_barcodes(fragments_file)

    ct_mtx = count(fragments_file, features[["chr", "start", "stop"]].values.tolist(), valid_bcs, fast)

    if fast:
        X = csr_matrix(ct_mtx)
    else:
        X = ct_mtx.tocsr()

    adata = ad.AnnData(X, obs=pd.DataFrame(index=valid_bcs), var=features)

    return adata


def window_mtx(fragments_file,
               valid_bcs=None,
               window_size=5000,
               species="human",
               fast=False):
    """
    Generates a count matrix based on the openness of equally sized bins of the genome (windows). The fragments file
    needs to be sorted.

    Args:
        fragments_file: path to fragments file
        valid_bcs: list of valid barcodes (optional)
        window_size: size of windows in bp; default: 5000 bp
        species: species to create the windows for (human or mouse); default: "human"; will be extended in the future
        fast: if True dense matrix will be used (faster but required more memory); default: False (sparse matrix)

    Returns:
        AnnData object
    """

    features = make_windows(window_size, chromosomes=species)

    features = [["chr{}".format(chrom), *window[:-1]] for chrom, windows in features.items() for window in windows]

    features = pd.DataFrame(features, columns=["chr", "start", "stop"])
    features["chr"] = features.chr.astype(str)

    features.index = features.apply(lambda row: "_".join([str(val) for val in row]), axis=1)

    features.sort_values(by=["chr", "start", "stop"], key=lambda col: col if col.dtype == np.int64 else col.str.lower(), inplace=True)

    if valid_bcs is None:
        valid_bcs = get_barcodes(fragments_file)

    ct_mtx = count(fragments_file, features.values.tolist(), valid_bcs, fast)

    if fast:
        X = csr_matrix(ct_mtx)
    else:
        X = ct_mtx.tocsr()

    adata = ad.AnnData(X, obs=pd.DataFrame(index=valid_bcs), var=features)

    return adata
