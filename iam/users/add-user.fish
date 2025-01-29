#!/usr/bin/env nix
#! nix shell nixpkgs#fish nixpkgs#kubectl nixpkgs#libressl nixpkgs#coreutils --command fish

function main -a username -a cluster -a role
    set private_key "$username.key"
    set csr "$username.csr"
    set cert "$username.crt"
    set role_bind "$username.yaml"

    # create private key & CSR
    openssl genpkey -out "$private_key" -algorithm Ed25519
    openssl req -new -key "$private_key" -out "$csr" -subj "/CN=$username/O=$cluster"

    # send CSR to cluster
    echo "
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: $username
spec:
  request: $(cat "$csr" | base64 | tr -d '\n')
  signerName: kubernetes.io/kube-apiserver-client
  usages:
    - client auth
" \
        | kubectl apply -f -

    # approve the CSR
    kubectl certificate approve "$username"

    kubectl get csr "$username" -o jsonpath='{.status.certificate}' | base64 -d >"$cert"

    # clean up the CSR
    kubectl delete csr "$username"

    # bind role to the new user
    echo "---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: '$username-$role'
subjects:
  - kind: User
    name: '$username'
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: '$role'
  apiGroup: rbac.authorization.k8s.io" >"$role_bind"

    # unstage all changes
    git reset
    # stage new resources
    git add "$role_bind"

    # ask user to verify staged changes
    git diff --cached
    read -l -P 'Does the above diff look correct? Can we commit and push? [y/N] ' confirm
    switch $confirm
        case Y y yes
            echo continuing
        case '*'
            echo aborting
            exit
    end

    # commit & push changes
    git commit -m "🛂 add user $username to cluster $cluster as $role"
    git push

    echo "Now transfer '$private_key' & '$cert' to your client computer, and run the following to configure kubectl:"
    echo "kubectl config set-credentials '$username' \\
        --client-key='$private_key' \\
        --client-certificate='$cert' \\
        --embed-certs=true"
end

set username "$argv[1]"
if test -z "$username"
    read -gP 'username: ' username
end

main "$username" doa-cluster owner
