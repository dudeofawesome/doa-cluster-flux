# Setup

## Bootstrap flux onto a new cluster

```sh
flux bootstrap github \
    --owner=dudeofawesome \
    --repository=doa-cluster-flux \
    --branch=main \
    --path=clusters/doa-cluster \
    --personal
```

## Setting up age decryption keys

#### Creating a new key

1. Generate the key

   ```sh
   age-keygen -o age.agekey
   ```

1. Add the key to the cluster

   ```sh
   cat age.agekey \
   | kubectl create secret generic sops-age \
       --namespace=flux-system \
       --from-file=age.agekey=/dev/stdin
   ```

1. Backup your key somewhere safe (1password?)

#### Using a pre-existing key

1. Add the key to the cluster

   ```sh
   op read op://orleans-brian-edgar-josh/doa-cluster/age.agekey \
   | kubectl create secret generic sops-age \
      --namespace=flux-system \
      --from-file=age.agekey=/dev/stdin
   ```
