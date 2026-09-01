# Versioned module consolidation

All numbered Python modules formerly stored as separate files under `marketing_diagnosis/` are embedded verbatim in `marketing_diagnosis/_versioned_runtime.py`. They are loaded lazily, so existing imports remain compatible without eagerly importing optional dependencies. New application code should import the stable API from `marketing_diagnosis.latest`.

Git history remains the authoritative backup for every removed file. The
generated runtime also retains every source verbatim and can restore the exact
files for maintenance without overwriting existing files:

```bash
python scripts/consolidate_versioned_modules.py --extract
```

After editing and testing the restored sources, regenerate and verify the
runtime with:

```bash
python scripts/consolidate_versioned_modules.py --apply
python scripts/consolidate_versioned_modules.py --check
```

| Original file | Compatibility module | SHA-256 |
|---|---|---|
| `ctrip_configuration_v63.py` | `marketing_diagnosis.ctrip_configuration_v63` | `c30f09c1bcfbc8d8d39d1572900cae2c35dd94b6e835f60519ee81541dec8fd4` |
| `ctrip_page_entry_v66.py` | `marketing_diagnosis.ctrip_page_entry_v66` | `bed06698c11f7232698c66b9464183a0e0789daa960dd75839659f8872c9194f` |
| `ctrip_promotion_v67.py` | `marketing_diagnosis.ctrip_promotion_v67` | `444829c027c6071e580e42711bf357683ffb1ab6ff335a13934fb17ecc1feaa2` |
| `ctrip_psi_v53.py` | `marketing_diagnosis.ctrip_psi_v53` | `27dc727c7a116d56ac450727300f36d4701e50bde4f51584bc7c104a95383d73` |
| `ctrip_report_v54.py` | `marketing_diagnosis.ctrip_report_v54` | `56fd0bd16e8bc872de52aab2f648b67952eae978bfc3c8a1f8a46c0b73aee33e` |
| `ctrip_reputation_radar_v2.py` | `marketing_diagnosis.ctrip_reputation_radar_v2` | `6d1c1fe53944a43b207df3311d97c2db34bc932aa6cb532243d082a2b8d7f1e9` |
| `ctrip_reputation_v64.py` | `marketing_diagnosis.ctrip_reputation_v64` | `7e91de777b4262d90de0385533e743eabf8500a190ec979f8bd4bfda1034cc11` |
| `ctrip_room_name_v65.py` | `marketing_diagnosis.ctrip_room_name_v65` | `d3c5048eb46e3a2fb5479b41c4a87c6d51a3623f0a850b78dce6a7705bc72766` |
| `ctrip_user_profile_v58.py` | `marketing_diagnosis.ctrip_user_profile_v58` | `36c05c2b227ba074e9ded9065019b53113574dc45fadf059b224f9539b8ac139` |
| `customer_excel_loader_v2.py` | `marketing_diagnosis.customer_excel_loader_v2` | `aae30db175c342bf282308d7acc38ea3500af2a6122166bb29849ff7158a56a1` |
| `data_v2.py` | `marketing_diagnosis.data_v2` | `7deec4f7e36a1942e5bdbd7b7397fd2381fc737beaec8386fd9fd7828d8c95c1` |
| `data_v3.py` | `marketing_diagnosis.data_v3` | `6da2f7da80fd123bdaa8d2038823e198f1457155a04abd02a97f56d36c73b3f5` |
| `data_v4.py` | `marketing_diagnosis.data_v4` | `96caee644926d402b87189068236df72597b4b37c4528f350d24cd20e120825f` |
| `db_loader_v10.py` | `marketing_diagnosis.db_loader_v10` | `2576ecee913cd5880b47239132252c2dd203508a13a13316c4ca892737489606` |
| `db_loader_v11.py` | `marketing_diagnosis.db_loader_v11` | `6a4686e06040c42f4af024fdad26a760ac4229230992939753f880418170750c` |
| `db_loader_v12.py` | `marketing_diagnosis.db_loader_v12` | `d0495a20a17f8fc37a051c06e341803c7486ae80d35cebd6491d12f53bff7117` |
| `db_loader_v13.py` | `marketing_diagnosis.db_loader_v13` | `39423157ff432742ae6b5050e61bdc22fe1fd44665297c120028ee3931c4e098` |
| `db_loader_v14.py` | `marketing_diagnosis.db_loader_v14` | `3f188eb4d28df437ae3e01e7d64a0782a604e77612c4292ffa4b6baafeedf29d` |
| `db_loader_v15.py` | `marketing_diagnosis.db_loader_v15` | `24772a32ba29a627d1a306dbc2d6c16b532357f082409915549f2079345097ed` |
| `db_loader_v16.py` | `marketing_diagnosis.db_loader_v16` | `74bf6795cb2441c5d41eae12489d180510d5767812e53804b6cf5619f6a7f51d` |
| `db_loader_v2.py` | `marketing_diagnosis.db_loader_v2` | `09e3c621ad1c597ca6e162b52a48f3657feb480be89101c11d8c4c08f8ae313a` |
| `db_loader_v3.py` | `marketing_diagnosis.db_loader_v3` | `eaef6746b388b4c9111151cec32dfec5c1fdd78c8e5d15879fe5e28c0f3d7906` |
| `db_loader_v4.py` | `marketing_diagnosis.db_loader_v4` | `c4208bc3cf6b2c800ba344098f786807a8db96a4d97ba4c97d7368915fcf4273` |
| `db_loader_v5.py` | `marketing_diagnosis.db_loader_v5` | `b4160bbff73ac01269ecffb8e9bfd85e004f0f6e9b283b6eaa5e6645a784fbcf` |
| `db_loader_v8.py` | `marketing_diagnosis.db_loader_v8` | `ba587163ccce18407be6d14f7b9e3a564bd544a0940ca999727058db7fef6028` |
| `db_loader_v9.py` | `marketing_diagnosis.db_loader_v9` | `58d8804699a0c26a4a04f95ef8825e88cdffb65ee578de0da32d0ff52233af93` |
| `db_loader_v9_legacy.py` | `marketing_diagnosis.db_loader_v9_legacy` | `6b6f7324cdec69b7e0050331acca5ddd011a470a130860995a4324f52959131c` |
| `dual_channel_report_v56.py` | `marketing_diagnosis.dual_channel_report_v56` | `bc4491d84ab5c87b6a0e857464e05280d0abe4726993cea34d135c9f0283cf29` |
| `excel_loader_v2.py` | `marketing_diagnosis.excel_loader_v2` | `8f18696af670ae326ad883e5bec97c5a911c7594c6e654f0bbb119c5889c8070` |
| `metrics_enrichment_v2.py` | `marketing_diagnosis.metrics_enrichment_v2` | `0cbf52441686084eaaad95f4b4f8a8d3906eb77eea9acb03645dec8199c67bd9` |
| `performance_trend_v54.py` | `marketing_diagnosis.performance_trend_v54` | `28ff57cd66a2041cda40d923d74c87ddf8411ac486a31c3c43ee98f99b56a9a0` |
| `performance_yoy_v37.py` | `marketing_diagnosis.performance_yoy_v37` | `47070ce9b1bcad109918ebe00149f9a444d6241d275aae3f052fc5e2961e8bed` |
| `performance_yoy_v40.py` | `marketing_diagnosis.performance_yoy_v40` | `b4dab8db621a1d9fcb252de7222f10d60019dcc440d4d477df8186d8b2d8ce00` |
| `promotion_performance_v46.py` | `marketing_diagnosis.promotion_performance_v46` | `289a820c890a58dc24303364351ed4999b291cfd1c36185bf544f580a5ff3d73` |
| `reporting_runtime_v51.py` | `marketing_diagnosis.reporting_runtime_v51` | `d45eeffc0f630f083eaeccb034e4931516e20f7b85bbb3144b6c54bf1230176d` |
| `reporting_runtime_v52.py` | `marketing_diagnosis.reporting_runtime_v52` | `e524d09fb84a431a4d43a7564642e7487c5452994ddfa43b71599d1c08331117` |
| `reporting_v10.py` | `marketing_diagnosis.reporting_v10` | `c42bd3247331909f2094914c05a82d69c33454d5134ff93a5cc6197b0306f81a` |
| `reporting_v11.py` | `marketing_diagnosis.reporting_v11` | `e7daab65a1d3644f85282bde4aa6c4b7215475765e3dc12f62584398296b4dba` |
| `reporting_v12.py` | `marketing_diagnosis.reporting_v12` | `4430d937adca590851e2ff81f7a35bcbaa33efb212bed9bf356fbb8a7aceb054` |
| `reporting_v13.py` | `marketing_diagnosis.reporting_v13` | `9c3cad4535c37b4f2b4d88dc560a0eb71a74e1a81ae0424b56972aca3d278ab1` |
| `reporting_v14.py` | `marketing_diagnosis.reporting_v14` | `4652796586d0a191ee79fe69f24facaf28a583c142149c2a8be511c266a468b5` |
| `reporting_v15.py` | `marketing_diagnosis.reporting_v15` | `b1f725bc17c7cab446d4db56f0969d85fd0abe87f25e3fc8e1c46e197b1ba9d9` |
| `reporting_v16.py` | `marketing_diagnosis.reporting_v16` | `c4dd0714afe1c39eca9289f1e5c4a7e373fa2aa09b9efc916e83fb7af81b754d` |
| `reporting_v17.py` | `marketing_diagnosis.reporting_v17` | `e22b3aa9ed1887305a5db3a21fb45223caa90458c0116bb702ae1744f408fa82` |
| `reporting_v18.py` | `marketing_diagnosis.reporting_v18` | `bf1cd727f1ddb7f7bafb7028f4e21b148ec2173302b36d3ab209342fdd42f6a3` |
| `reporting_v19.py` | `marketing_diagnosis.reporting_v19` | `decc8a4b34b4ec8c55cb3fb4775aa53743f7a3fb3ed62626da2233fe76bad251` |
| `reporting_v2.py` | `marketing_diagnosis.reporting_v2` | `87f560df19675c07e1d91bf776ea29cf7b2f94ecd8bfe90023d7a0e00347ea5a` |
| `reporting_v20.py` | `marketing_diagnosis.reporting_v20` | `9cf8e72cf473a54de9cfcab4c786dea7c7dfb4df22131fea2057b3d36470de52` |
| `reporting_v21.py` | `marketing_diagnosis.reporting_v21` | `0a09fd18fb0a77a0a5cc638fba8096be4713f4b259dcdce310c2b8973eca75c1` |
| `reporting_v22.py` | `marketing_diagnosis.reporting_v22` | `0273205b6452a5cfa4c7d333bd34633853fd1bf0f4bf07e76de303c2323d3640` |
| `reporting_v23.py` | `marketing_diagnosis.reporting_v23` | `dd1a249ce24eab1f10ff5f176af03465101d43d3fc6f8de9f7056bb95cb39493` |
| `reporting_v24.py` | `marketing_diagnosis.reporting_v24` | `b7e018b87be00d398d2d44526f07529a6d6e4b581275587df2bcdf767567b8e4` |
| `reporting_v25.py` | `marketing_diagnosis.reporting_v25` | `946e1b8d187be8f2e95c83b29f90c485505e94cc163b60e94a3c993f8c1f5a6c` |
| `reporting_v26.py` | `marketing_diagnosis.reporting_v26` | `5c4b92729798d20a47bab0e146e738a7092527689b1a443779ba338e5848357e` |
| `reporting_v27.py` | `marketing_diagnosis.reporting_v27` | `19e1482fc7e790b0b3505334849ad90c2dea375e4f878c541f18b5ce9e3f6f1f` |
| `reporting_v28.py` | `marketing_diagnosis.reporting_v28` | `cf9a2f89437b4ed95d4730bb4311f15a94d554e70b9f600d2976cfa9ee3b0323` |
| `reporting_v29.py` | `marketing_diagnosis.reporting_v29` | `9441f544406246a1be3c743322716c64908e198903457075e231a5d52e4e6bcd` |
| `reporting_v3.py` | `marketing_diagnosis.reporting_v3` | `dbb5cc0902e569d499256282e39ea0cb76e45aa07f9d8688c964b30c9a4b7956` |
| `reporting_v30.py` | `marketing_diagnosis.reporting_v30` | `278b91135d6b07679dab157462cc2d914ea7e0ea8e6e552ddc4c5bce1d641835` |
| `reporting_v31.py` | `marketing_diagnosis.reporting_v31` | `df65a5cb97ae3e817423f9442dbdd0e8f45b1bdf39b723b99767fa7224492296` |
| `reporting_v32.py` | `marketing_diagnosis.reporting_v32` | `c4cd4e55ff02ea0cd10db43614a8f2daa5ff3a249bfcf585a7636e3fe604c56e` |
| `reporting_v33.py` | `marketing_diagnosis.reporting_v33` | `be8e647e862c63822a70989ed3b3d64372f2f87e79898386d98af717ca4a1ab3` |
| `reporting_v34.py` | `marketing_diagnosis.reporting_v34` | `2492cdd9fc9a636f87369795b102c7ceb1cd3d2a2a2a1f8f36059d54883f8253` |
| `reporting_v35.py` | `marketing_diagnosis.reporting_v35` | `7a1bfdb9745e251fcceac7ec641462cefa339bcc7490378bfc04e1adb37d30db` |
| `reporting_v36.py` | `marketing_diagnosis.reporting_v36` | `38ce43c249ad22abcd27a635f054b79a67d9f7c7ac9258a65ea51ec3039a9f53` |
| `reporting_v37.py` | `marketing_diagnosis.reporting_v37` | `c9215eca36c72754828ba81391bfa7f97e05fcef8d954473e607794559b2a470` |
| `reporting_v38.py` | `marketing_diagnosis.reporting_v38` | `d0bde87b189c26e9dbfead8ffe373542b498cf779c97a357b6a6639882125638` |
| `reporting_v39.py` | `marketing_diagnosis.reporting_v39` | `106c3ed68d5457e297ad07d9fe88a14411f2a1f799f2ea3b6096ef98cef9aa63` |
| `reporting_v4.py` | `marketing_diagnosis.reporting_v4` | `5d6a960ef43047211dd49a14b76ff4c646ae5a4b3d0c55b8af3dbbc07c60a8b0` |
| `reporting_v40.py` | `marketing_diagnosis.reporting_v40` | `99a9fe9831a91926b43b42f600984222d7f4f12e813749bd45d47099cf8f7a21` |
| `reporting_v5.py` | `marketing_diagnosis.reporting_v5` | `2765e60d37f74d86c1199d16a8ac84a996ea7fe8817b992265b80ee476e1fea6` |
| `reporting_v6.py` | `marketing_diagnosis.reporting_v6` | `5e37bcd84e9593a69c0ceaef53c9cb89e4042f3c4214944dd1d5624ccd181f37` |
| `reporting_v8.py` | `marketing_diagnosis.reporting_v8` | `fd1d703ade66b24315e4ff3bb8db43b503e3397d4f26bafd4af7d7884dd16c78` |
| `reporting_v9.py` | `marketing_diagnosis.reporting_v9` | `d5e573c295336c919dbf143bbb3662268b5db4f3e5ab6fe69495978dbff10b8f` |
| `review_yesterday_v45.py` | `marketing_diagnosis.review_yesterday_v45` | `d21c3b22ddd94f8205e4c758267661aae41c93556abc543d34259cd1a31a06fd` |
| `room_name_manual_v43.py` | `marketing_diagnosis.room_name_manual_v43` | `96dcf8613723cff75f59db94260ef6a343dc251e5caf97c1e539bbeb13aa02bc` |
| `room_type_classification_v42.py` | `marketing_diagnosis.room_type_classification_v42` | `de7c3396ace2bdfcac1588f7ae483f16051c473e51e4cdd6050a0f6f277cdf9e` |
| `rules_v3.py` | `marketing_diagnosis.rules_v3` | `a8cd5c8ea470d8bb2bbc19d10d8d1ea39ccd5bb9727b6e8fc680bdbab150ab52` |
| `rules_v4.py` | `marketing_diagnosis.rules_v4` | `d04ba6399850cf39394c50711ea2f0068f1e2d276b21563b1804820324a3d193` |
| `rules_v5.py` | `marketing_diagnosis.rules_v5` | `4078c202ad130e4915085f40a9ec7739fdc2b91161ead7c655db7605bf16f44e` |
| `visual_diagnosis_v10.py` | `marketing_diagnosis.visual_diagnosis_v10` | `0a04e765e549f940f3fc9d4948abaaf25c4ab23905ad63536be62a60087b92b2` |
| `visual_diagnosis_v11.py` | `marketing_diagnosis.visual_diagnosis_v11` | `5c8886895654fc271b2a3ae70b4ae8531fc563dcce5776e28f41e1e5d0729326` |
| `visual_diagnosis_v12.py` | `marketing_diagnosis.visual_diagnosis_v12` | `3f541864d4d7414169e405a7261adf3f09cb3250ae34225a71d21f2878b3524b` |
| `visual_diagnosis_v13.py` | `marketing_diagnosis.visual_diagnosis_v13` | `1ee74193321f71d7a863a60a0f915c27976efd11c71aa8cb3ebeaa672e2e2262` |
| `visual_diagnosis_v14.py` | `marketing_diagnosis.visual_diagnosis_v14` | `7094f3a5563a945e99e85b7588db9403f96b2ce3adf2042fa27b9804ca2e0486` |
| `visual_diagnosis_v15.py` | `marketing_diagnosis.visual_diagnosis_v15` | `9df8ff1b3cd37a691ff9cee8f6a8fcbe3f9062b37c1b0cf60f4f80c91a666aa3` |
| `visual_diagnosis_v16.py` | `marketing_diagnosis.visual_diagnosis_v16` | `6d01a6e9a309f58a2459045f70b27cd90f8fbd827398084bbdd3f9ef52c6f896` |
| `visual_diagnosis_v17.py` | `marketing_diagnosis.visual_diagnosis_v17` | `54136a668961a8262dd38cc3baad161e4b5e1c97246a070954efc5a96fead20c` |
| `visual_diagnosis_v18.py` | `marketing_diagnosis.visual_diagnosis_v18` | `4108975504f8b5816472c5f192226db79b6e2c7f8d7d3f74112c104cfc17ea05` |
| `visual_diagnosis_v19.py` | `marketing_diagnosis.visual_diagnosis_v19` | `f5f2bdb62e01a981a84f90e311bc2f7ed53c084d30e607b8b604adf269eecf10` |
| `visual_diagnosis_v2.py` | `marketing_diagnosis.visual_diagnosis_v2` | `82db45fe2b12adc31576a7daaebd481b248bc8244e5ba26cdba4decc8b7148cd` |
| `visual_diagnosis_v20.py` | `marketing_diagnosis.visual_diagnosis_v20` | `acc5633ca181e09db85f3d50f6a492aebf14d015a8bd49cd9fb16b880d463857` |
| `visual_diagnosis_v3.py` | `marketing_diagnosis.visual_diagnosis_v3` | `6007c6da178c1ba58242c7937b01bb07421a88b2ed0e6af416a67c4e61d2f37b` |
| `visual_diagnosis_v4.py` | `marketing_diagnosis.visual_diagnosis_v4` | `13b8b3e851268eb611d3034da4f315e50d5dd9fb55269d0cc07ca054fadf40f5` |
| `visual_diagnosis_v5.py` | `marketing_diagnosis.visual_diagnosis_v5` | `8eb41a31176fc9a2ab30f859d447c6e3aecc48584604133f7e49bc4c5c9a313c` |
| `visual_diagnosis_v6.py` | `marketing_diagnosis.visual_diagnosis_v6` | `819e9d94fa57f16c086a713ff603afd0f2299176d1465f04b53853034ccc2f48` |
| `visual_diagnosis_v7.py` | `marketing_diagnosis.visual_diagnosis_v7` | `0bdfd71e226707b4776ca930e7b5af229f67f09033d267f9a1d60d313eeafcc7` |
| `visual_diagnosis_v8.py` | `marketing_diagnosis.visual_diagnosis_v8` | `27ecf86ab178853b94413ae6e4472b20d1f408ac9f90946ab9be1f731b93b4ec` |
| `visual_diagnosis_v9.py` | `marketing_diagnosis.visual_diagnosis_v9` | `cd7b6d1c0b93392b1f5a5caeff22386179b699e5d435008cd1825bbcd6992a7d` |
